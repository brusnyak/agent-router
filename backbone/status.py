"""`backbone status`: one-glance view of what the router is doing (for terminals, UIs and notifications).

`--json` for machines, `--brief` for a 2-line text widget, `--details` for full debug lines.
Reads only: backbone.db (runs, jobs) and the monitor snapshots written by `backbone monitor --write`.
Nothing here starts a worker, touches the network, or writes to the database.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from typing import Dict, List

STALE_RUNNING_S = 6 * 3600
WINDOW_S = 24 * 3600
ACTIVE_LIMIT = 10
HOST_FRESH_S = 900  # monitor snapshot younger than this is "fresh"


def _home() -> str:
    return os.path.expanduser(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router"))


def _db_path() -> str:
    return os.path.join(_home(), "data", "backbone.db")


_ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    """Strip terminal/control characters (ANSI escapes included) and collapse whitespace; width-safe plain text."""
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r"\s+", " ", _CTRL.sub("", _ANSI.sub("", text))).strip()


def _meta(text: str) -> Dict:
    try:
        m = json.loads(text or "{}")
    except (ValueError, TypeError):
        return {}
    return m if isinstance(m, dict) else {}


def collect(db_path: str = "", now: float = 0.0, per_worker: int = 8, active_limit: int = ACTIVE_LIMIT) -> Dict:
    now = now or time.time()
    out: Dict = {
        "ts": now,
        "available": False,
        "error": "",
        "source": "",
        "counts": {},
        "workers": {},
        "jobs": {},
        "hosts": {},
        "active_tasks": [],
        "active_counts": {"running": 0, "queued": 0},
        "stale_running": 0,
    }
    path = db_path or _db_path()
    sources: List[str] = []
    if not os.path.exists(path):
        out["error"] = "router database unavailable"
        out["source"] = ",".join(sources)
        return out
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "runs" not in tables or "jobs" not in tables:
                raise sqlite3.Error("schema missing runs/jobs tables")
            run_ids = {r[0] for r in con.execute("SELECT id FROM runs WHERE state='running'")}
            window = now - WINDOW_S

            # --- runs: historical counts (24h) + all active runs regardless of age ---
            for r in con.execute(
                "SELECT id, command, prompt, worker, state, created, updated, meta FROM runs "
                "WHERE created >= ? OR state='running' ORDER BY created DESC", (window,)
            ):
                rid, command, prompt, worker, state, created, updated, meta = r
                if created >= window:
                    out["counts"][state] = out["counts"].get(state, 0) + 1
                if state == "running":
                    task: Dict = {
                        "id": rid,
                        "title": _clean(command or prompt or "")[:60] or rid,
                        "state": state,
                        "age": max(0, int(now - created)),
                        "heartbeat_age_s": max(0, int(now - updated)),
                    }
                    if now - created > STALE_RUNNING_S:
                        out["stale_running"] += 1
                    if worker:
                        task["worker"] = _clean(worker)
                    m = _meta(meta)
                    if "progress" in m:
                        task["progress"] = m["progress"]
                    if "gate" in m:
                        task["gate"] = _clean(str(m["gate"]))
                    out["active_tasks"].append(task)
                # per-worker 24h history (retained in details only)
                if created >= window:
                    lst: List[str] = out["workers"].setdefault(worker or "?", [])
                    if len(lst) < per_worker:
                        lst.append(state)

            # Preserve counts as run history; jobs retain their separate aggregate.
            for r in con.execute(
                "SELECT id, text, owner, state, run_id, created, updated, opts FROM jobs"
            ).fetchall():
                jid, text, owner, state, run_id, created, updated, opts = r
                linked = run_id is not None and run_id in run_ids
                if state in ("pending", "queued", "running") and not linked:
                    task = {
                        "id": jid,
                        "title": _clean(text)[:60] or jid,
                        "state": state,
                        "age": max(0, int(now - created)),
                        "heartbeat_age_s": max(0, int(now - updated)),
                    }
                    if owner:
                        task["worker"] = _clean(owner)
                    m = _meta(opts)
                    for key in ("progress", "gate", "gate_name"):
                        if key in m:
                            task["gate" if key == "gate_name" else key] = _clean(str(m[key]))
                    out["active_tasks"].append(task)

            out["active_counts"] = {
                "running": sum(t["state"] == "running" for t in out["active_tasks"]),
                "queued": sum(t["state"] in ("pending", "queued") for t in out["active_tasks"]),
            }
            out["active_tasks"].sort(key=lambda t: (t["state"] != "running", t["age"]))
            out["active_tasks"] = out["active_tasks"][:active_limit]

            out["jobs"] = dict(
                con.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state").fetchall()
            )
            out["source"] = "sqlite"
            out["available"] = True
        finally:
            con.close()
    except sqlite3.Error as exc:
        out["error"] = str(exc)[:120]
        out["source"] = ",".join(sources)
        return out

    # --- monitor snapshots: read-only file reads, freshness = age/error, not hub reachability ---
    mon = os.path.join(_home(), "monitor")
    if os.path.isdir(mon):
        for fn in sorted(os.listdir(mon)):
            if fn.endswith(".json"):
                try:
                    fp = os.path.join(mon, fn)
                    with open(fp, "r") as f:
                        snap = json.load(f)
                    if not isinstance(snap, dict):
                        continue
                    stamp = snap.get("ts")
                    if isinstance(stamp, str):
                        sampled = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                    elif isinstance(stamp, (float, int)):
                        sampled = stamp
                    else:
                        sampled = os.path.getmtime(fp)
                    age = max(0, round(now - sampled, 1))
                    out["hosts"][_clean(str(snap.get("host", fn[:-5])))] = {
                        "load1": round(float(snap.get("load1", 0)), 2),
                        "cpus": snap.get("cpus"),
                        "mem_avail_mb": round(float(snap.get("mem_avail_mb", 0))),
                        "age_s": age,
                        "error": _clean(str(snap.get("error", ""))),
                        "freshness": "error"
                        if snap.get("error")
                        else ("fresh" if age <= HOST_FRESH_S else "stale"),
                    }
                except (OSError, ValueError, TypeError):
                    continue
    return out


_GLYPH = {"done": "●", "failed": "✗", "running": "◐", "blocked": "▫", "queued": "·", "pending": "·"}


def _task_line(t: Dict) -> str:
    parts = [str(t.get("id", "")), t.get("title", "") or ""]
    if t.get("worker"):
        parts.append(t["worker"])
    parts.append(str(t.get("state", "")))
    if t.get("age") is not None:
        parts.append(f"{t['age']}s")
    if "progress" in t:
        parts.append(f"progress:{t['progress']}")
    if t.get("gate"):
        parts.append(f"gate configured:{t['gate']}")
    if t.get("heartbeat_age_s") is not None:
        parts.append(f"heartbeat {t['heartbeat_age_s']}s ago")
    return " · ".join(_clean(str(p)) for p in parts if p != "")


def _host_labels(s: Dict) -> List[str]:
    labels: List[str] = []
    for h, v in sorted(s.get("hosts", {}).items(), key=lambda item: item[1].get("freshness") == "fresh"):
        if v.get("error"):
            labels.append(f"{h}: error {_clean(str(v['error']))[:40]}")
        else:
            age = v.get("age_s")
            labels.append(f"{h}: {v.get('freshness', '?')} {age}s" if age is not None else h)
    return labels


def brief(s: Dict) -> List[str]:
    if not s.get("available"):
        lines = ["Router unavailable"]
        if s.get("error"):
            lines.append(_clean(s["error"]))
        return lines
    tasks = s.get("active_tasks", [])
    active = s.get("active_counts", {})
    running = active.get("running", 0)
    queued = active.get("queued", 0)
    labels: List[str] = []
    if s.get("source"):
        labels.append("local")
    labels.extend(_host_labels(s))
    line1 = f"Router {running} running · {queued} queued"
    if labels:
        line1 += " | " + " · ".join(labels[:3])
    lines = [line1]
    if tasks:
        t = tasks[0]
        lines.append(f"{t['state']}: {t['title']} · {t.get('worker', 'unassigned')} · {t['age']}s")
    else:
        stale = [
            h
            for h, v in s.get("hosts", {}).items()
            if v.get("error") or (v.get("age_s") or 0) > HOST_FRESH_S
        ]
        if stale:
            lines.append("hosts stale: " + ", ".join(stale[:3]))
    return lines


def details(s: Dict) -> List[str]:
    if not s.get("available"):
        lines = ["Router unavailable"]
        if s.get("error"):
            lines.append(_clean(s["error"]))
        return lines
    lines = ["counts (24h): " + (", ".join(f"{k} {v}" for k, v in sorted(s.get("counts", {}).items())) or "none")]
    lines.append("jobs (all states): " + (", ".join(f"{k} {v}" for k, v in sorted(s.get("jobs", {}).items())) or "none"))
    lines.append(f"active tasks (bounded {len(s.get('active_tasks', []))}):")
    for t in s.get("active_tasks", []):
        lines.append("  - " + _task_line(t))
    lines.append("workers (24h history):")
    for w, states in sorted(s.get("workers", {}).items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {_clean(w)}: " + "".join(_GLYPH.get(st, "?") for st in reversed(states)))
    lines.append("hosts (monitor freshness):")
    for h, v in sorted(s.get("hosts", {}).items()):
        lines.append(
            f"  {h}: {v.get('freshness', '?')} age={v.get('age_s')}s load={v.get('load1')} "
            + (f"error={_clean(str(v.get('error')))}" if v.get("error") else "")
        )
    return lines


def main(argv=None) -> int:
    argv = list(argv or [])
    s = collect()
    if "--json" in argv:
        print(json.dumps(s))
    elif "--details" in argv:
        print("\n".join(details(s)))
    else:
        print("\n".join(brief(s)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
