"""Key policy: lease NIM keys with per-key concurrency caps, cooldown on failure, retry + failover.

Deterministic: preferred key first, then the next free one. No gateway process.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")


ENV_FILES = ("~/.env", "~/.config/agent-router/env")  # owner's dev machine, then the hub's systemd EnvironmentFile


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


class Transient(Exception):
    """Worth retrying, ideally on another key: 429, 5xx, timeouts, queue/safety-screen errors."""
    retry_after: Optional[float] = None  # seconds, from an HTTP 429 Retry-After header


class KeyPool:
    def __init__(self, names: List[str], max_concurrent: int = 0, cooldown_s: float = 0.0,
                 env: Optional[dict] = None, wait_s: float = 120.0, rpm_limit: int = 30,
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

    def value(self, name: str) -> str:
        return self.env.get(name, "")

    def status(self) -> Dict[str, dict]:
        now = self.clock()
        return {n: {"present": n in self.names, "cooling_s": max(0, round(self._cool.get(n, 0) - now, 1)),
                    "in_window": self._count(n, now),
                    **self.stats.get(n, {})} for n in self.all_names}

    def _count(self, n: str, now: float) -> int:
        w = self._win.get(n, [])
        w[:] = [t for t in w if t > now - 60]
        return len(w)

    def _order(self, prefer: Optional[str], avoid: Optional[str]) -> List[str]:
        now = self.clock()
        order = [n for n in self.names]
        if prefer in order:
            order.remove(prefer)
            order.insert(0, prefer)
        # round-robin primary: rotate starting at cursor so keys get even distribution
        self._rr = (self._rr + 1) % len(order)
        rr_order = order[self._rr:] + order[:self._rr]
        rr_order.sort(key=lambda n: (self._cool[n] > now, n == avoid, self._inflight.get(n, 0), self._count(n, now)))  # cooled/avoided last, then fewest in-flight, then fewest in window
        return rr_order

    @contextlib.contextmanager
    def lease(self, prefer: Optional[str] = None, avoid: Optional[str] = None):
        if not self.names:
            raise RuntimeError("no NIM keys present in environment (" + ", ".join(self.all_names) + ")")
        deadline = self.clock() + self.wait_s
        got = None
        while got is None:
            with self._mu:
                now = self.clock()
                for n in self._order(prefer, avoid):
                    if self._count(n, now) >= self.rpm_limit:
                        continue
                    if n in self._sem and not self._sem[n].acquire(blocking=False):
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
