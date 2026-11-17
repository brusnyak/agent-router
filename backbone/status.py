"""`backbone status`: one-glance view of what the router is doing (for terminals, UIs and notifications).

`--json` for machines (the web UI mini graph reads this), `--brief` for a 2-line text widget.
Reads only: backbone.db (runs, jobs) and the monitor snapshots written by `backbone monitor --write`.
Nothing here starts a worker or touches the network.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from typing import Dict, List

STALE_RUNNING_S = 6 * 3600
WINDOW_S = 24 * 3600


def _home() -> str:
    return os.path.expanduser(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router"))


def _db_path() -> str:
    return os.path.join(_home(), "data", "backbone.db")


def _short(worker: str) -> str:
    return (worker or "?").replace("browser+", "b+").replace(":NIM_", ":n")


def collect(db_path: str = "", now: float = 0.0, per_worker: int = 8) -> Dict:
    now = now or time.time()
    out: Dict = {"ts": now, "counts": {}, "stale_running": 0, "workers": {}, "jobs": {}, "hosts": {}}
    path = db_path or _db_path()
    if os.path.exists(path):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            rows = con.execute("SELECT worker, state, created FROM runs WHERE created >= ? ORDER BY created DESC",
                               (now - WINDOW_S,)).fetchall()
            counts: Dict[str, int] = {}
            for _w, state, _c in rows:
                counts[state] = counts.get(state, 0) + 1
            out["counts"] = counts
            for w, state, created in rows:
                lst: List[str] = out["workers"].setdefault(w or "?", [])
                if len(lst) < per_worker:
                    lst.append(state)
            out["stale_running"] = sum(
                1 for (c,) in con.execute("SELECT created FROM runs WHERE state='running'") if now - c > STALE_RUNNING_S)
            try:
                out["jobs"] = dict(con.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state").fetchall())
            except sqlite3.Error:
                pass
            con.close()
        except sqlite3.Error as exc:
            out["error"] = str(exc)[:120]
    mon = os.path.join(_home(), "monitor")
    if os.path.isdir(mon):
        for fn in sorted(os.listdir(mon)):
            if fn.endswith(".json"):
                try:
                    snap = json.load(open(os.path.join(mon, fn)))
                    out["hosts"][snap.get("host", fn[:-5])] = {
                        "load1": round(float(snap.get("load1", 0)), 2),
                        "cpus": snap.get("cpus"),
                        "mem_avail_mb": round(float(snap.get("mem_avail_mb", 0))),
                        "age_s": round(now - os.path.getmtime(os.path.join(mon, fn))),
                        "error": snap.get("error", ""),
                    }
                except (OSError, ValueError):
                    continue
    return out


_GLYPH = {"done": "●", "failed": "✗", "running": "◐", "blocked": "▫", "queued": "·"}


def brief(s: Dict) -> List[str]:
    c = s.get("counts", {})
    hosts = " ".join(f"{h} {v['load1']:.1f}" + ("!" if v.get("error") or v.get("age_s", 0) > 900 else "")
                     for h, v in s.get("hosts", {}).items())
    stale = f" · {s['stale_running']} stale" if s.get("stale_running") else ""
    line1 = (f"⎇ router ▸ {c.get('running', 0)} running · {c.get('done', 0)}✓ {c.get('failed', 0)}✗ "
             f"{c.get('blocked', 0)} blocked (24h){stale}" + (f" │ {hosts}" if hosts else ""))
    parts = [f"{_short(w)} " + "".join(_GLYPH.get(st, "?") for st in reversed(states))
             for w, states in sorted(s.get("workers", {}).items(), key=lambda kv: -len(kv[1]))[:6]]
    return [line1] + ([" · ".join(parts)] if parts else [])


def main(argv=None) -> int:
    argv = list(argv or [])
    s = collect()
    if "--json" in argv:
        print(json.dumps(s))
    else:
        print("\n".join(brief(s)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
