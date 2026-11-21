"""Read-only factory feed. See docs/factory-status.md for the source contract."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

UNKNOWN = "unknown"
TERMINAL = {"done", "failed", "blocked", "cancelled"}


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _stamp(value):
    if _number(value):
        try:
            datetime.fromtimestamp(value)
            return float(value)
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None


def _object(path):
    value = _json(path)
    return value if isinstance(value, dict) else {}


def _rows(path, query, args=()):
    # URI escaping matters for configured paths containing '?' or '#'.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(query, args)]


def _query(path, query, args=()):
    try:
        return _rows(path, query, args)
    except (sqlite3.Error, OSError, ValueError):
        return None


def _router(path, now):
    result = {"running": UNKNOWN, "queued": UNKNOWN, "last_runs": UNKNOWN,
              "last_activity": UNKNOWN}
    runs = _query(path, "SELECT id, worker, state, created, updated FROM runs ORDER BY created DESC")
    jobs = _query(path, "SELECT id, state, run_id, created, updated FROM jobs")
    activity = []
    if runs is not None:
        history = []
        for r in runs:
            start = _stamp(r["created"])
            if start is not None:
                activity.append(start)
            end = _stamp(r["updated"])
            if r["state"] in TERMINAL and end is not None:
                activity.append(end)
        for r in runs[:10]:
            steps = _query(path, "SELECT ok FROM steps WHERE run_id=? AND kind='gate' ORDER BY id DESC LIMIT 1", (r["id"],))
            gate = UNKNOWN
            if steps and steps[0]["ok"] in (0, 1):
                gate = "pass" if steps[0]["ok"] else "fail"
            stamp = _stamp(r["created"])
            history.append({"id": r["id"], "worker": r["worker"] or UNKNOWN,
                            "state": r["state"], "gate": gate,
                            "age_s": max(0, now - stamp) if stamp is not None else UNKNOWN})
        result["last_runs"] = history
    if runs is not None and jobs is not None:
        running = {r["id"] for r in runs if r["state"] == "running"}
        result["running"] = len(running) + sum(
            j["state"] == "running" and j["run_id"] not in running for j in jobs)
        result["queued"] = sum(j["state"] in ("pending", "queued") and j["run_id"] not in running for j in jobs)
    if jobs is not None:
        activity.extend(stamp for j in jobs if j["state"] in TERMINAL
                        if (stamp := _stamp(j["updated"])) is not None)
    if activity:
        result["last_activity"] = max(activity)
    # Never-started queues age from their oldest enqueue, not from epoch zero.
    queued_since = min((_stamp(j["created"]) for j in (jobs or [])
                        if j["state"] in ("pending", "queued", "running")
                        and _stamp(j["created"]) is not None), default=None)
    return result, queued_since


def _node(path, now, fresh_s):
    snap = _object(path)
    stamp = _stamp(snap.get("ts"))
    age = max(0, now - stamp) if stamp is not None else UNKNOWN
    return {"freshness": ("stale" if snap.get("error") or age > fresh_s else "fresh")
            if _number(age) else UNKNOWN,
            "age_s": age, "load": snap.get("load1") if _number(snap.get("load1")) else UNKNOWN}


def _idle(path):
    out = {"last_tick": UNKNOWN, "state": UNKNOWN}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return out
    # JSON, timestamp-prefixed JSON, and pretty-printed CLI JSON are supported.
    decoder = json.JSONDecoder()
    text = "\n".join(lines)
    last = None
    offset = 0
    while (start := text.find("{", offset)) >= 0:
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except ValueError:
            offset = start + 1
            continue
        offset = start + consumed
        if isinstance(value, dict) and isinstance(value.get("state"), str):
            prefix = text[:start].splitlines()
            stamp = _stamp(value.get("ts", value.get("timestamp")))
            if stamp is None and prefix:
                stamp = _stamp(prefix[-1].strip())
            last = {"last_tick": stamp if stamp is not None else UNKNOWN, "state": value["state"]}
    return last or out


def _career(runs_dir, db, digest_dir, now):
    out = {"last_daily_run": UNKNOWN, "prepared_today": UNKNOWN,
           "applied_today": UNKNOWN, "last_digest_path": UNKNOWN}
    try:
        receipts = [_object(p) for p in runs_dir.glob("*.json")]
        valid = [(ts, r) for r in receipts if (ts := _stamp(r.get("completed_at"))) is not None]
        today = datetime.fromtimestamp(now).date()
        if valid:
            out["last_daily_run"] = max(ts for ts, _ in valid)
            todays = [r for ts, r in valid if datetime.fromtimestamp(ts).date() == today]
            # Count distinct prepared application IDs across repeated daily runs.
            if todays and all(isinstance(r.get("prepared"), list) for r in todays):
                ids = []
                for r in todays:
                    for entry in r["prepared"]:
                        identity = entry
                        if isinstance(entry, dict):
                            identity = next((entry[k] for k in ("id", "application_id", "listing_id")
                                             if entry.get(k)), entry)
                        ids.append(json.dumps(identity, sort_keys=True))
                out["prepared_today"] = len(set(ids))
    except OSError:
        pass
    rows = _query(db, "SELECT submitted_at FROM applications")
    if rows is not None:
        stamps = [_stamp(r["submitted_at"]) for r in rows if r["submitted_at"] is not None]
        if all(s is not None for s in stamps):
            out["applied_today"] = sum(datetime.fromtimestamp(s).date() == datetime.fromtimestamp(now).date() for s in stamps)
    try:
        digests = list(digest_dir.glob("*-batch.md"))
        if digests:
            out["last_digest_path"] = str(max(digests, key=lambda p: p.stat().st_mtime))
    except OSError:
        pass
    return out


def _upwork(path):
    out = {"last_run": UNKNOWN, "counts_by_grade": UNKNOWN}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return out
    blocks = list(re.finditer(r"(?m)^- (\d{4}-\d\d-\d\d[ T]\d\d:\d\d).*", text))
    if blocks:
        latest = max(blocks, key=lambda m: m.group(1))
        end = next((m.start() for m in blocks if m.start() > latest.start()), len(text))
        stamp = _stamp(latest.group(1))
        if stamp is not None:
            out["last_run"] = stamp
            grades = re.findall(r"(?m)^\s*- \[([ABCD])\]", text[latest.end():end])
            out["counts_by_grade"] = {g: grades.count(g) for g in "ABCD"}
    return out


def collect(config_path=None, *, now=None):
    """Collect optional sources without creating files, databases, or processes."""
    now = time.time() if now is None else now
    home = Path(os.path.expanduser(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router")))
    config_path = Path(config_path).expanduser() if config_path is not None else home / "factory.json"
    cfg = _object(config_path)

    def path(key, default):
        value = cfg.get(key, default)
        p = Path(value).expanduser() if isinstance(value, str) and value else home / "unconfigured" / key
        return p if p.is_absolute() else config_path.parent / p

    router, queued_since = _router(path("router_db", str(home / "data/backbone.db")), now)
    limits = _object(path("limits", str(home / "limits.json")))
    idle_s = cfg.get("idle_threshold_s", limits.get("idle_minutes", 10) * 60
                     if _number(limits.get("idle_minutes", 10)) else 600)
    if not _number(idle_s) or idle_s <= 0:
        idle_s = 600
    fresh_s = cfg.get("node_fresh_s", 900)
    if not _number(fresh_s) or fresh_s <= 0:
        fresh_s = 900
    monitor = path("monitor_dir", str(home / "monitor"))
    nodes = {name: _node(path(name + "_snapshot", str(monitor / (name + ".json"))), now, fresh_s)
             for name in ("mac", "oracle")}
    inbox = _object(path("inbox_monitor", ""))
    last_run = _stamp(inbox.get("last_run"))
    events = inbox.get("events", UNKNOWN)
    if not isinstance(events, list) and not (_number(events) and events >= 0):
        events = UNKNOWN
    approvals = _query(path("outreach_db", str(home / "data/approvals.db")),
                       "SELECT COUNT(*) AS n FROM cards WHERE kind='outreach' AND decision IN ('pending','later')")
    backlog_path = path("backlog", str(home / "backlog.jsonl"))
    backlog = UNKNOWN
    try:
        records = [json.loads(line) for line in backlog_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if all(isinstance(r, dict) and isinstance(r.get("prompt"), str) for r in records):
            backlog = len(records)
    except (OSError, ValueError, UnicodeError):
        pass
    counts = [router["running"], router["queued"], backlog]
    has_backlog = any(_number(n) and n > 0 for n in counts)
    activity = router["last_activity"]
    if activity == UNKNOWN:
        activity = queued_since
        if activity is None and _number(backlog) and backlog > 0:
            try:
                activity = backlog_path.stat().st_mtime
            except OSError:
                activity = None
    stalled = UNKNOWN
    if has_backlog and _number(activity):
        # Missing router history cannot establish inactivity.
        if router["last_runs"] != UNKNOWN and router["queued"] != UNKNOWN:
            stalled = now - activity >= idle_s
    elif all(_number(n) and n == 0 for n in counts):
        stalled = False
    return {"ts": now, "router": router, "nodes": nodes,
            "idle_tick": _idle(path("idle_tick_log", str(home / "idle-tick.log"))),
            "limits": limits or UNKNOWN,
            "career_agent": _career(path("career_runs", ""), path("career_db", ""), path("career_digest_dir", ""), now),
            "upwork_scan": _upwork(path("upwork_index", "")),
            "inbox_monitor": {"last_run": last_run if last_run is not None else UNKNOWN, "events": events},
            "outreach_queue": {"pending_approvals": approvals[0]["n"] if approvals else UNKNOWN},
            "backlog": backlog, "idle_threshold_s": idle_s, "stalled": stalled}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backbone factory-status")
    parser.add_argument("--json", action="store_true", help="emit one JSON document (default)")
    parser.add_argument("--config", help="factory.json location")
    args = parser.parse_args(argv)
    print(json.dumps(collect(args.config), allow_nan=False))
    return 0
