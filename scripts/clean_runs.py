"""One-off cleanup: reap stale (dead-lease) running runs and clear zombie blocked runs
that poll a dead health endpoint. Safe, read-mostly; prints a summary."""
from __future__ import annotations

import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/.agent-router/data/backbone.db")

if len(sys.argv) > 1 and sys.argv[1] == "--apply":
    APPLY = True
else:
    APPLY = False
    print("DRY RUN (no changes). Pass --apply to commit.")


def main() -> None:
    con = sqlite3.connect(f"file:{DB}?mode=rw", uri=True)
    con.row_factory = sqlite3.Row
    now = time.time()

    stale = con.execute(
        "SELECT id, worker, prompt, lease_until FROM runs WHERE state='running' AND lease_until < ?",
        (now,),
    ).fetchall()
    blocked_zombies = con.execute(
        "SELECT id, worker, prompt FROM runs WHERE state='blocked' AND worker='browser+pi:NIM_2'"
    ).fetchall()
    other_blocked = con.execute(
        "SELECT id, worker, prompt FROM runs WHERE state='blocked' AND worker!='browser+pi:NIM_2'"
    ).fetchall()

    print(f"stale running (lease expired): {len(stale)}")
    for r in stale[:10]:
        print("  ", r["id"], r["worker"], (r["prompt"] or "")[:60])
    print(f"zombie blocked (browser+pi:NIM_2 health-poller): {len(blocked_zombies)}")
    print(f"other blocked (kept): {len(other_blocked)}")

    if not APPLY:
        return

    n_stale = 0
    for r in stale:
        con.execute("UPDATE runs SET state='failed', error='reaped: lease expired', updated=? WHERE id=?",
                    (now, r["id"]))
        n_stale += 1

    n_zombie = 0
    for r in blocked_zombies:
        con.execute("UPDATE runs SET state='failed', error='reaped: dead health endpoint', updated=? WHERE id=?",
                    (now, r["id"]))
        n_zombie += 1

    con.commit()
    print(f"reaped {n_stale} stale, marked {n_zombie} zombie blocked as failed")
    con.close()


if __name__ == "__main__":
    main()
