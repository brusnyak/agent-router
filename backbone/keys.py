"""Key policy: lease NIM keys with per-key concurrency caps, cooldown on failure, retry + failover.

Deterministic: preferred key first, then the next free one. No gateway process.

Also hosts SwitchyardRouter: an opt-in in-process port of NVIDIA NeMo Switchyard's routing model
(failure cooldown + fallback candidates) over KeyPool. KeyPool still owns the actual lease/rpm
accounting; SwitchyardRouter only picks target order per route and reports outcomes.
"""
from __future__ import annotations
import contextlib
import fcntl
import json
import os
import re
import threading
import time
import tempfile
import uuid
from typing import Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")


ENV_FILES = ("~/.env", "~/.config/agent-router/env")  # owner's dev machine, then the hub's systemd EnvironmentFile
STATE_FILE = os.path.expanduser("~/.agent-router/data/key_state.json")  # cross-process rpm state (names only)
SHARED_TTL_S = 90  # shared state older than this is considered stale

# <PROVIDER>_[API_]KEY|TOKEN|SECRET[_N]  or  <PROVIDER>_N  (NIM_1). Names only: values are never read here.
_KEY_NAME = re.compile(r"^(?P<p>[A-Z][A-Z0-9]*?)(?:_API)?_(?:KEY|TOKEN|SECRET)(?:_?\d+)?$|^(?P<p2>[A-Z][A-Z0-9]*)_\d+$")


def env_key_names(paths=ENV_FILES, environ=None) -> List[str]:
    """Names (never values) of key-like variables in the given env files plus the process environment."""
    names = set(k for k in (os.environ if environ is None else environ))
    for path in paths:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if line.startswith("export "):
                        line = line[7:].lstrip()
                    if line and not line.startswith("#") and "=" in line:
                        names.add(line.split("=", 1)[0].strip())
        except OSError:
            continue
    return sorted(n for n in names if _KEY_NAME.match(n))


def with_discovered(names: List[str], paths=ENV_FILES, environ=None, pattern: str = r"NIM_\d+") -> List[str]:
    """Configured names first (their order is the owner's preference), then every other key matching `pattern` found in the env files or the
    process environment, numerically ordered. New keys (NIM_4, NIM_5, ...) join the pool with no config edit. Names only."""
    found = sorted((n for n in env_key_names(paths, environ) if re.fullmatch(pattern, n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    return list(names) + [n for n in found if n not in names]


def discover_keys(paths=ENV_FILES, environ=None, known: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, object]]:
    """Group key names by provider, whatever the provider is. -> {provider: {"keys": [names], "llm": bool, "base_url": str}}.
    `known` maps provider -> {base_url, style, aliases} (config/providers.yaml); names not in it are still reported (llm False)."""
    known = known or {}
    alias = {a: p for p, v in known.items() for a in v.get("aliases", [])}
    out: Dict[str, Dict[str, object]] = {}
    for name in env_key_names(paths, environ):
        m = _KEY_NAME.match(name)
        prov = (m.group("p") or m.group("p2")).lower()
        prov = alias.get(prov, prov)
        slot = out.setdefault(prov, {"keys": [], "llm": prov in known, "base_url": (known.get(prov) or {}).get("base_url", "")})
        slot["keys"].append(name)
    return out


def load_named(names: List[str], paths=ENV_FILES) -> Dict[str, str]:
    """Only the named keys from the owner's env files (same contract as ~/.claude/scripts/with-env), so the router needs no wrapper.
    Values go into the in-process pool only; never logged. First file that has a key wins."""
    out: Dict[str, str] = {}
    for path in ([paths] if isinstance(paths, str) else paths):
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if line.startswith("export "):
                        line = line[7:]
                    k, sep, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if sep and k in names and v and k not in out:
                        out[k] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
        except OSError:
            pass
    return out


def _shared_load() -> dict:
    """Load cross-process key state from the shared JSON file (fcntl guarded, names only, no values)."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_SH)
            try:
                data = json.load(fh)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, ValueError):
        return {}


def _shared_save(data: dict) -> None:
    """Persist cross-process key state atomically (names only, no values)."""
    parent = os.path.dirname(STATE_FILE)
    os.makedirs(parent, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=parent,
                                         prefix='key-state-', delete=False) as fh:
            tmp = fh.name
            json.dump(data, fh)
        os.replace(tmp, STATE_FILE)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _shared_update(fn):
    """Lock the entire read/modify/replace, not the replaced JSON inode."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = _shared_load()
            result = fn(data)
            _shared_save(data)
            return result
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _live_leases(entry):
    leases = {}
    stored = entry.get('leases', {})
    if not isinstance(stored, dict):
        return leases
    for token, pid in stored.items():
        try:
            if int(pid) <= 0:
                continue
            os.kill(int(pid), 0)
        except ProcessLookupError:
            continue
        except (PermissionError, OverflowError):
            pass
        except (TypeError, ValueError):
            continue
        leases[token] = pid
    return leases


def shared_claim(name, token, candidates, limit=0, rpm_limit=0, now=None):
    """Atomically spread active processes across available aliases."""
    now = time.time() if now is None else now
    def update(data):
        for item in data.values():
            if isinstance(item, dict):
                item['leases'] = _live_leases(item)
        entry = data.setdefault(name, {})
        stored_window = entry.get('window', [])
        window = [t for t in stored_window if isinstance(t, (int, float)) and now - t <= 60] if isinstance(stored_window, list) else []
        if rpm_limit > 0 and len(window) >= rpm_limit:
            return False
        active = len(entry.get('leases', {}))
        if limit > 0 and active >= limit:
            return False
        # With an unlimited cap, share only after every alternative is busy.
        if active and any(not data.get(n, {}).get('leases') for n in candidates if n != name):
            return False
        entry.setdefault('leases', {})[token] = os.getpid()
        if rpm_limit > 0:
            entry['window'] = window + [now]
            entry['ts'] = now
        return True
    return _shared_update(update)


def shared_release(name, token):
    def update(data):
        data.get(name, {}).get('leases', {}).pop(token, None)
    _shared_update(update)


def _shared_prune(data: dict, now: float) -> dict:
    """Drop entries older than SHARED_TTL_S so dead processes don't hold rpm forever."""
    out = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts", 0)
        if now - ts <= SHARED_TTL_S or entry.get('cool_until', 0) > now or _live_leases(entry):
            out[name] = entry
    return out


def shared_count(name: str, now: Optional[float] = None) -> int:
    """Cross-process sliding-window request count for a key name (last 60 s)."""
    if now is None:
        now = time.time()
    data = _shared_load()
    data = _shared_prune(data, now)
    entry = data.get(name, {})
    window = entry.get("window", [])
    if not isinstance(window, list):
        return 0
    return sum(1 for t in window if now - t <= 60)


def shared_register(name: str, now: Optional[float] = None) -> None:
    """Register a cross-process request for a key name (called at lease time)."""
    if now is None:
        now = time.time()
    def update(data):
        entry = data.setdefault(name, {})
        window = entry.get('window', [])
        entry['window'] = [t for t in window if now - t <= 60] + [now] if isinstance(window, list) else [now]
        entry['ts'] = now
    _shared_update(update)


def shared_cool(name: str, until: float, now: Optional[float] = None) -> None:
    """Mark a key as cooling until `until` (cross-process, e.g. after 401/429)."""
    if now is None:
        now = time.time()
    def update(data):
        entry = data.setdefault(name, {})
        entry['cool_until'] = until
        entry['ts'] = now
    _shared_update(update)


def shared_is_cooling(name: str, now: Optional[float] = None) -> bool:
    """True if a key is cooling cross-process (rejected/limited, never preferred)."""
    if now is None:
        now = time.time()
    data = _shared_load()
    data = _shared_prune(data, now)
    entry = data.get(name, {})
    return bool(entry.get("cool_until", 0) > now)


def shared_cooling_seconds(name: str, now: float) -> float:
    entry = _shared_load().get(name, {})
    return max(0, entry.get('cool_until', 0) - now) if isinstance(entry, dict) else 0


class Transient(Exception):
    """Worth retrying, ideally on another key: 429, 5xx, timeouts, queue/safety-screen errors."""
    retry_after: Optional[float] = None  # seconds, from an HTTP 429 Retry-After header


class KeyPool:
    def __init__(self, names: List[str], max_concurrent: int = 0, cooldown_s: float = 0.0,
                 env: Optional[dict] = None, wait_s: float = 120.0, rpm_limit: int = 40,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.clock, self.sleep, self.rpm_limit = clock, sleep, rpm_limit
        self._rr: int = 0  # round-robin cursor for fair key distribution
        if env is None:  # default: process env, topped up with the named keys the shell did not export
            env = {**load_named([n for n in names if not os.environ.get(n)]), **os.environ}
        self.env = env
        self.names = [n for n in names if self.env.get(n)]
        self.all_names = list(names)
        self.cooldown_s = cooldown_s
        self.wait_s = wait_s
        self._win: Dict[str, List[float]] = {n: [] for n in self.names}  # request timestamps, sliding 60 s
        self._sem = {n: threading.BoundedSemaphore(max_concurrent) for n in self.names} if max_concurrent > 0 else {}
        self._cool: Dict[str, float] = {n: 0.0 for n in self.names}
        self.stats: Dict[str, Dict[str, int]] = {n: {"ok": 0, "fail": 0} for n in self.names}
        self._mu = threading.Lock()
        self._inflight: Dict[str, int] = {}  # leases currently held (a long agent run holds its key for minutes)
        self._limit = max_concurrent

    def value(self, name: str) -> str:
        return self.env.get(name, "")

    def status(self) -> Dict[str, dict]:
        now = self.clock()
        return {n: {"present": n in self.names, "cooling_s": round(max(0, self._cool.get(n, 0) - now, shared_cooling_seconds(n, now)), 1),
                    "in_window": max(self._count(n, now), shared_count(n, now)),
                    **self.stats.get(n, {})} for n in self.all_names}

    def _count(self, n: str, now: float) -> int:
        w = self._win.get(n, [])
        w[:] = [t for t in w if t > now - 60]
        return len(w)

    def _order(self, prefer: Optional[str], avoid: Optional[str]) -> List[str]:
        now = self.clock()
        order = [n for n in self.names]
        # preferred key first, but only when it is not already held by a concurrent lease;
        # otherwise prefer is a hint and we spread to the least-loaded key.
        first: Optional[str] = None
        if prefer and prefer in order and self._inflight.get(prefer, 0) == 0 and not shared_is_cooling(prefer, now):   # a cooling (rejected/limited) key is never the preferred one
            order.remove(prefer)
            first = prefer
        # round-robin + fewest-load among the rest (contention spreads across keys)
        if order:
            self._rr = (self._rr + 1) % len(order)
            rr_rest = order[self._rr:] + order[:self._rr]
            rr_rest.sort(
                key=lambda n: (
                    shared_is_cooling(n, now),
                    n == avoid,
                    self._inflight.get(n, 0),
                    shared_count(n, now),
                )
            )
        else:
            rr_rest = order
        return ([first] if first else []) + rr_rest

    @contextlib.contextmanager
    def lease(self, prefer: Optional[str] = None, avoid: Optional[str] = None):
        if not self.names:
            raise RuntimeError("no NIM keys present in environment (" + ", ".join(self.all_names) + ")")
        deadline = self.clock() + self.wait_s
        got = None
        token = uuid.uuid4().hex
        while got is None:
            with self._mu:
                now = self.clock()
                eligible = [n for n in self._order(prefer, avoid)
                            if self._cool.get(n, 0) <= now and not shared_is_cooling(n, now)]
                for n in eligible:
                    if max(self._count(n, now), shared_count(n, now)) >= self.rpm_limit:
                        continue
                    if n in self._sem and not self._sem[n].acquire(blocking=False):
                        continue
                    try:
                        claimed = shared_claim(n, token, eligible, self._limit, self.rpm_limit, now)
                    except BaseException:
                        if n in self._sem:
                            self._sem[n].release()
                        raise
                    if not claimed:
                        if n in self._sem:
                            self._sem[n].release()
                        continue
                    self._win[n].append(now)
                    self._inflight[n] = self._inflight.get(n, 0) + 1
                    got = n
                    break
            if got is None:
                if self.clock() > deadline:
                    raise Transient("all keys at rpm limit or busy past wait budget")
                self.sleep(0.2)
        try:
            yield got
        finally:
            try:
                shared_release(got, token)
            finally:
                with self._mu:
                    self._inflight[got] = max(0, self._inflight.get(got, 1) - 1)
                if got in self._sem:
                    self._sem[got].release()

    def report(self, name: str, ok: bool, retry_after: Optional[float] = None) -> None:
        with self._mu:
            self.stats[name]["ok" if ok else "fail"] += 1
            if not ok:
                cd = retry_after if retry_after is not None else self.cooldown_s
                if cd:
                    self._cool[name] = self.clock() + cd
                    shared_cool(name, self.clock() + cd)

    def call(self, fn: Callable[[str, str], T], prefer: Optional[str] = None,
             retries: int = 1, backoff_s: float = 3.0) -> T:
        """fn(key_name, key_value). Transient errors retry (max `retries`), moving to another key."""
        last: Optional[Exception] = None
        used: Optional[str] = None
        attempts = max(retries + 1, len(self.names))  # every key gets a chance (SPEC D4)
        for attempt in range(attempts):
            try:
                with self.lease(prefer=prefer if attempt == 0 else None, avoid=used) as name:
                    used = name
                    try:
                        out = fn(name, self.value(name))
                        self.report(name, True)
                        return out
                    except Transient as e:
                        self.report(name, False, retry_after=e.retry_after)
                        last = e
            except Transient as e:
                last = e
            if attempt < attempts - 1:
                time.sleep(backoff_s * min(attempt + 1, 3))
        raise Transient(f"failed after {attempts} attempts: {last}")


class SwitchyardRoute:
    """One Switchyard-style route: target keys + per-key failure cooldown + fallback order.

    Ports Switchyard's routing model (failure_cooldown_ms, max_retries, fallback candidates)
    into the router's KeyPool without running a gateway. Used to decide which NIM key a route
    sends traffic to, with per-key cooldown after exhausted retries.
    """

    def __init__(self, keys: List[str], pool: KeyPool, max_retries: int = 2,
                 failure_cooldown_s: float = 5.0, prefer: Optional[str] = None):
        self.keys = list(keys)
        self.pool = pool
        self.max_retries = max_retries
        self.failure_cooldown_s = failure_cooldown_s
        self.prefer = prefer
        self._cool: Dict[str, float] = {k: 0.0 for k in keys}
        self._stats: Dict[str, Dict[str, int]] = {k: {"ok": 0, "fail": 0} for k in keys}
        self._mu = threading.Lock()

    def order(self, now: Optional[float] = None) -> List[str]:
        """Key order for this route: preferred key first, then cooled/available keys by fewest failures."""
        n = now or self.pool.clock()
        first: List[str] = []
        rest: List[str] = []
        if self.prefer and self.prefer in self.keys:
            first.append(self.prefer)
        for k in self.keys:
            if k == self.prefer:
                continue
            rest.append(k)
        rest.sort(key=lambda k: (self._cool[k] > n, self._stats[k]["fail"], k))
        return first + rest

    def report(self, key: str, ok: bool, retry_after: Optional[float] = None) -> None:
        with self._mu:
            self._stats[key]["ok" if ok else "fail"] += 1
            if not ok:
                cd = retry_after if retry_after is not None else self.failure_cooldown_s
                if cd:
                    self._cool[key] = self.pool.clock() + cd


class SwitchyardRouter:
    """Opt-in routing decision layer over KeyPool (Switchyard ported in-process).

    Routes map a task class to an ordered key list. On a transient failure the route moves to
    the next key; a failed key cools for failure_cooldown_s. KeyPool still owns the actual
    lease/rpm accounting — SwitchyardRouter only picks the target order and reports outcomes.
    """

    def __init__(self, pool: KeyPool, routes: Dict[str, List[str]],
                 default_route: Optional[str] = None, max_retries: int = 2,
                 failure_cooldown_s: float = 5.0):
        self.pool = pool
        self.routes = {name: SwitchyardRoute(keys, pool, max_retries, failure_cooldown_s,
                                             routes.get("_prefer", {}).get(name) if isinstance(routes.get("_prefer"), dict) else None)
                       for name, keys in routes.items() if name != "_prefer"}
        self.default_route = default_route
        self._prefer = routes.get("_prefer", {}) if isinstance(routes.get("_prefer"), dict) else {}

    def route_for(self, task_class: str) -> SwitchyardRoute:
        return self.routes.get(task_class) or self.routes.get(self.default_route) or \
            SwitchyardRoute(list(self.pool.names), self.pool)

    def call(self, fn: Callable[[str, str], T], task_class: str = "default",
             retries: Optional[int] = None) -> T:
        """fn(key_name, key_value). Route to the task class's key order, failover on transient."""
        route = self.route_for(task_class)
        retries = self.max_retries if retries is None else retries
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            for key in route.order():
                if key not in self.pool.names:
                    continue
                try:
                    with self.pool.lease(prefer=key if attempt == 0 else None) as name:
                        try:
                            out = fn(name, self.pool.value(name))
                            route.report(name, True)
                            return out
                        except Transient as e:
                            route.report(name, False, retry_after=e.retry_after)
                            last = e
                except Transient:
                    continue
            if attempt < retries:
                time.sleep(min(1.0, route.failure_cooldown_s) * (attempt + 1))
        raise Transient(f"SwitchyardRouter failed after {retries + 1} attempts: {last}")

    def status(self) -> Dict[str, dict]:
        out = {}
        for name, route in self.routes.items():
            out[name] = {k: dict(v, cooling_s=max(0, round(route._cool.get(k, 0) - self.pool.clock(), 1)))
                         for k, v in route._stats.items()}
        return out
