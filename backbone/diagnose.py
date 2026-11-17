"""Read-only queue diagnosis and explicit, conditional lease recovery."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import time


def router_home():
    return Path(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router")).expanduser()


def diagnose(con, *, now=None, home=None, agents=None):
    from .discover import discover

    now = time.time() if now is None else now
    home = Path(home) if home is not None else router_home()
    agents = discover()["agents"] if agents is None else agents
    findings = []
    columns = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    rows = con.execute("SELECT * FROM jobs")
    names = [c[0] for c in rows.description] if hasattr(rows, "description") else list(columns)
    for row in rows:
        job = dict(row) if hasattr(row, "keys") else dict(zip(names, row))
        attempt = job.get("attempt", job.get("attempts", 0)) or 0
        reasons = []
        if job["state"] == "running" and 0 < (job.get("lease_until") or 0) < now:
            reasons.append("STUCK_RUNNING")
        if job["state"] in ("pending", "queued") and now - job["created"] > 1800:
            reasons.append("STALE_QUEUED")
        if attempt >= 3:
            reasons.append("REPEATED_FAILURE")
        try:
            opts = json.loads(job.get("opts") or "{}")
        except (ValueError, TypeError):
            opts = {}
        worker = job.get("worker") or (opts.get("worker", "") if isinstance(opts, dict) else "")
        if worker and worker not in agents:
            reasons.append("NO_WORKER")
        findings.extend({"id": job["id"], "reason": reason, "attempt": attempt,
                         "lease_until": job.get("lease_until"), "state": job["state"]}
                        for reason in reasons)
    work = home / "data" / "work"
    if work.is_dir():
        for directory in sorted(work.iterdir()):
            if directory.is_dir() and not directory.is_symlink() and now - directory.stat().st_mtime > 21600:
                findings.append({"path": str(directory), "reason": "ORPHAN_WORKTREE"})
    return findings


def recover(con, *, apply=False, now=None, home=None):
    now = time.time() if now is None else now
    home = Path(home) if home is not None else router_home()
    columns = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    attempt_column = "attempt" if "attempt" in columns else "attempts"
    queued_state = "queued" if "attempt" in columns else "pending"
    actions = []
    for finding in diagnose(con, now=now, home=home, agents={}):
        if finding["reason"] != "STUCK_RUNNING" or finding["attempt"] >= 3:
            continue
        action = {**finding, "new_attempt": finding["attempt"] + 1, "apply": apply}
        if apply:
            # Compare both attempt and lease: a renewed or completed claim must win.
            cur = con.execute(
                f"UPDATE jobs SET state=?, {attempt_column}={attempt_column}+1, lease_until=NULL, updated=? "
                f"WHERE id=? AND state='running' AND lease_until=? AND {attempt_column}=?",
                (queued_state, now, finding["id"], finding["lease_until"], finding["attempt"]))
            con.commit()
            if cur.rowcount != 1:
                continue
            path = home / "data" / "recover.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({**action, "ts": now}) + "\n")
        actions.append(action)
    return actions


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backbone")
    parser.add_argument("action", choices=("diagnose", "recover"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and args.action != "recover":
        parser.error("--apply requires recover")
    path = router_home() / "data" / "backbone.db"
    if not path.exists():
        print("[]" if args.json else "no jobs database")
        return 0
    mode = "rw" if args.apply else "ro"
    with sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True) as con:
        con.row_factory = sqlite3.Row
        result = (recover(con, apply=args.apply) if args.action == "recover" else diagnose(con))
    if args.json:
        print(json.dumps(result))
    else:
        for item in result:
            print(json.dumps(item))
    return 0
