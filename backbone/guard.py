"""Unattended-safety guard. One choke point in front of every worker dispatch:

  kill switch   any PAUSE file present  -> nothing runs ("paused: <file>")
  budgets       calls/day and USD/day, counted in a small SQLite ledger next to the router DB -> "budget: ..."
  unattended    BACKBONE_UNATTENDED=1: every worker is forced read-only; expert (own-subscription) workers are denied
                unless listed in BACKBONE_UNATTENDED_ALLOW; a default daily call cap applies if none is configured

Fail closed in unattended mode, permissive in interactive use (no budget configured = no cap). Stdlib only.
Config (backbone.yaml):  guard: {pause_files: [...], calls_per_day: N, usd_per_day: X, ledger: true}
Env overrides: BACKBONE_BUDGET_CALLS, BACKBONE_BUDGET_USD, BACKBONE_UNATTENDED, BACKBONE_UNATTENDED_ALLOW, BACKBONE_PAUSE_FILES."""
from __future__ import annotations

import os
import math
import sqlite3
import sys
import time

from .paths import vault_dir
from typing import Dict, List, Optional

DEFAULT_PAUSE = ["~/.agent-router/PAUSE", vault_dir("pages", "dispatch-PAUSE")]
EXPERT = {"claude", "codex"}              # run on the owner's own subscription
UNATTENDED_DEFAULT_CALLS = 200            # applies only when unattended and nothing else is configured


class Blocked(Exception):
    """A dispatch the guard refuses. The message becomes the worker result text."""


def prepared_research(opts: dict, cfg: Optional[dict] = None) -> bool:
    """Only text-in/text-out prepared packets may use the unattended run graph."""
    return (opts.get("prepared") is True and opts.get("read_only") is True
            and str(opts.get("worker", "")).partition(":")[0] == "nim-chat"
            and not opts.get("gate") and not opts.get("gate_name")
            and opts.get("use_vault") is False and opts.get("escalate") == ""
            and not any((cfg or {}).get("hooks", {}).get(k) for k in ("pre_run", "post_run")))


def _env(env: Optional[dict]) -> dict:
    return os.environ if env is None else {**os.environ, **env}


def pause_files(cfg: Optional[dict] = None, env: Optional[dict] = None) -> List[str]:
    raw = _env(env).get("BACKBONE_PAUSE_FILES")
    files = raw.split(":") if raw is not None else ((cfg or {}).get("guard", {}).get("pause_files") or DEFAULT_PAUSE)
    return [os.path.expanduser(f) for f in files if f]


def paused(cfg: Optional[dict] = None, env: Optional[dict] = None) -> Optional[str]:
    return next((f for f in pause_files(cfg, env) if os.path.exists(f)), None)


def unattended(env: Optional[dict] = None) -> bool:
    return str(_env(env).get("BACKBONE_UNATTENDED", "")).lower() in ("1", "true", "yes")


def _num(env: dict, name: str, cfg_val, cast):
    raw = env.get(name, cfg_val)
    if raw in (None, ""):
        return None
    try:
        value = cast(raw)
        if value < 0 or not math.isfinite(value):
            raise ValueError()
        return value
    except (TypeError, ValueError, OverflowError):
        raise Blocked(f"budget: invalid {name}") from None


class Ledger:
    """calls(ts, day, worker, ok, cost): one row per dispatched worker call."""

    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.con = sqlite3.connect(path, timeout=10)
        self.con.execute("CREATE TABLE IF NOT EXISTS calls(ts REAL, day TEXT, worker TEXT, ok INTEGER, cost REAL)")
        self.con.execute("CREATE INDEX IF NOT EXISTS calls_day ON calls(day)")

    @staticmethod
    def day(now: Optional[float] = None) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(now or time.time()))

    def record(self, worker: str, ok: bool, cost: float = 0.0, now: Optional[float] = None) -> None:
        now = now or time.time()
        self.con.execute("INSERT INTO calls VALUES (?,?,?,?,?)", (now, self.day(now), worker, int(bool(ok)), float(cost or 0)))
        self.con.commit()

    def today(self, now: Optional[float] = None) -> Dict[str, dict]:
        rows = self.con.execute("SELECT worker, COUNT(*), COALESCE(SUM(cost),0) FROM calls WHERE day=? GROUP BY worker", (self.day(now),))
        return {w: {"calls": n, "usd": round(c, 4)} for w, n, c in rows}

    def reserve(self, worker, read_only, cfg=None, env=None):
        """Serialize check + reservation across processes; crashed calls still count."""
        try:
            self.con.execute("BEGIN IMMEDIATE")
            ro = check(worker, read_only, cfg, env, ledger=self)
            now = time.time()
            cur = self.con.execute("INSERT INTO calls VALUES (?,?,?,?,?)",
                                   (now, self.day(now), worker, 0, 0.0))
            self.con.commit()
            return ro, cur.lastrowid
        except BaseException:
            self.con.rollback()
            raise

    def finish(self, reservation, ok, cost=0.0):
        cost = float(cost)
        if not math.isfinite(cost) or cost < 0:
            raise Blocked("budget: invalid reported cost")
        self.con.execute("UPDATE calls SET ok=?, cost=? WHERE rowid=?",
                         (int(bool(ok)), cost, reservation))
        self.con.commit()


def ledger_path(cfg: Optional[dict]) -> Optional[str]:
    """Next to the router DB, so tests/stand-ins with no DB never write into the real ledger."""
    db = (cfg or {}).get("db")
    if not db or (cfg or {}).get("guard", {}).get("ledger") is False:
        return None
    p = os.path.expanduser(db)
    return os.path.join(os.path.dirname(os.path.abspath(p)), "ledger.db") if os.path.isabs(p) else None


def check(kind: str, read_only: bool, cfg: Optional[dict] = None, env: Optional[dict] = None,
          ledger: Optional[Ledger] = None, now: Optional[float] = None) -> bool:
    """Raise Blocked, or return the effective read_only flag (forced True when unattended)."""
    env = _env(env)
    hit = paused(cfg, env)
    if hit:
        raise Blocked(f"paused: kill file {hit} exists (remove it or run `backbone guard resume`)")
    un = unattended(env)
    if un:
        allow = {a.strip() for a in str(env.get("BACKBONE_UNATTENDED_ALLOW", "")).split(",") if a.strip()}
        if kind in EXPERT and kind not in allow:
            raise Blocked(f"unattended: expert worker '{kind}' is not allowed (set BACKBONE_UNATTENDED_ALLOW={kind} to permit)")
        read_only = True
    g = (cfg or {}).get("guard", {})
    calls_cap = _num(env, "BACKBONE_BUDGET_CALLS", g.get("calls_per_day"), int)
    if calls_cap is None and un:
        calls_cap = UNATTENDED_DEFAULT_CALLS
    usd_cap = _num(env, "BACKBONE_BUDGET_USD", g.get("usd_per_day"), float)
    if calls_cap == 0 or usd_cap == 0:
        raise Blocked("budget: zero cap")
    if (un or calls_cap is not None or usd_cap is not None) and ledger is None:
        raise Blocked("budget: ledger unavailable")
    if (calls_cap is not None or usd_cap is not None) and ledger is not None:
        used = ledger.today(now)
        n = sum(v["calls"] for v in used.values())
        usd = ledger.con.execute("SELECT COALESCE(SUM(cost),0) FROM calls WHERE day=?",
                                 (ledger.day(now),)).fetchone()[0]
        if calls_cap is not None and n >= calls_cap:
            raise Blocked(f"budget: {n} calls today >= cap {calls_cap}")
        if usd_cap is not None and usd >= usd_cap:
            raise Blocked(f"budget: ${usd:.2f} today >= cap ${usd_cap:.2f}")
    return read_only


def status(cfg: Optional[dict] = None, env: Optional[dict] = None) -> dict:
    env = _env(env)
    lp = ledger_path(cfg)
    used = Ledger(lp).today() if lp and os.path.exists(lp) else {}
    return {"paused": paused(cfg, env), "unattended": unattended(env), "pause_files": pause_files(cfg, env),
            "today": used, "calls_today": sum(v["calls"] for v in used.values())}


def main(argv: Optional[List[str]] = None) -> int:
    import json
    cmd = (argv or ["status"])[0]
    cfg = None
    try:
        from .core import load_config
        cfg = load_config()
    except Exception:
        pass
    first = os.path.expanduser(pause_files(cfg)[0])
    if cmd == "pause":
        os.makedirs(os.path.dirname(first), exist_ok=True)
        open(first, "w").write(time.strftime("paused %Y-%m-%dT%H:%M:%S\n"))
        print("paused:", first)
    elif cmd == "resume":
        gone = []
        for f in pause_files(cfg):
            if os.path.exists(f):
                os.remove(f)
                gone.append(f)
        print("resumed; removed:", gone or "nothing was paused")
    elif cmd == "status":
        print(json.dumps(status(cfg), indent=2, default=str))
    else:
        print("usage: backbone guard [status|pause|resume]", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
