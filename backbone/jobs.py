"""Durable job inbox + daemon. `submit` from anywhere (CLI, MCP, another machine's ssh); the daemon runs jobs,
survives restarts (orphaned jobs are requeued, max attempts then ticket), and writes a heartbeat file.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from typing import List, Optional

from .core import Backbone
from .notify import notify
from . import tg

MAX_ATTEMPTS = 2


class Jobs:
    def __init__(self, bb: Backbone):
        self.bb = bb
        self.con = bb.con
        self.owner = uuid.uuid4().hex[:8]  # this daemon instance

    def submit(self, text: str, **opts) -> str:
        jid = uuid.uuid4().hex[:8]
        self.con.execute("INSERT INTO jobs(id,text,opts,state,attempts,created,updated) VALUES (?,?,?,?,?,?,?)",
                         (jid, text, json.dumps(opts), "pending", 0, time.time(), time.time()))
        self.con.commit()
        return jid

    def list(self, limit: int = 20) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id,state,attempts,run_id,substr(text,1,60) AS text FROM jobs ORDER BY created DESC LIMIT ?", (limit,))]

    def adopt_orphans(self) -> int:
        """Jobs left 'running' by a dead daemon: retry up to MAX_ATTEMPTS, then block with a ticket."""
        n = 0
        for r in self.con.execute("SELECT * FROM jobs WHERE state='running' AND owner!=?", (self.owner,)).fetchall():
            run = self.bb.runs.get(r["run_id"]) if r["run_id"] else None
            if run and run["state"] == "done":  # finished before the daemon died: never repeat completed work
                self.con.execute("UPDATE jobs SET state='done', updated=? WHERE id=?", (time.time(), r["id"]))
            elif r["attempts"] >= MAX_ATTEMPTS:
                if r["run_id"]:
                    self.bb.runs.ticket(r["run_id"], "daemon died repeatedly during this job", "split the task or change worker")
                self.con.execute("UPDATE jobs SET state='blocked', updated=? WHERE id=?", (time.time(), r["id"]))
            else:
                self.con.execute("UPDATE jobs SET state='pending', updated=? WHERE id=?", (time.time(), r["id"]))
            n += 1
        self.con.commit()
        return n

    def _claim(self) -> Optional[dict]:
        r = self.con.execute("SELECT * FROM jobs WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
        if not r:
            return None
        cur = self.con.execute("UPDATE jobs SET state='running', owner=?, attempts=attempts+1, updated=? "
                               "WHERE id=? AND state='pending'", (self.owner, time.time(), r["id"]))
        self.con.commit()
        return dict(r) if cur.rowcount == 1 else None  # lost the race: someone else claimed it

    def _execute(self, job: dict) -> None:
        opts = json.loads(job["opts"] or "{}")
        try:
            def link(rid: str) -> None:
                self.con.execute("UPDATE jobs SET run_id=? WHERE id=?", (rid, job["id"]))
                self.con.commit()

            prior = self.bb.runs.get(job["run_id"]) if job["run_id"] else None
            if prior and prior["state"] in ("running", "failed", "blocked"):
                res = self.bb.resume(job["run_id"])  # checkpointed: continues, never repeats completed steps
            else:
                res = self.bb.run(job["text"], on_start=link, **opts)
            state = "done" if res.get("state") == "done" else "blocked"
            self.con.execute("UPDATE jobs SET state=?, run_id=?, updated=? WHERE id=?",
                             (state, res.get("run", ""), time.time(), job["id"]))
        except Exception as e:  # the Backbone already tickets; never leave the job 'running'
            state = "blocked"
            self.con.execute("UPDATE jobs SET state='blocked', updated=? WHERE id=?", (time.time(), job["id"]))
        self.con.commit()
        notify(tg.report(job, state, locals().get("res")))

    def tick(self, max_parallel: int = 2, wait: bool = False) -> int:
        running = self.con.execute("SELECT COUNT(*) n FROM jobs WHERE state='running' AND owner=?", (self.owner,)).fetchone()["n"]
        threads = []
        for _ in range(max(0, max_parallel - running)):
            job = self._claim()
            if not job:
                break
            t = threading.Thread(target=self._execute, args=(job,), daemon=True)
            t.start()
            threads.append(t)
        if wait:
            [t.join() for t in threads]
        return len(threads)

    def daemon(self, poll_s: float = 5.0, max_parallel: int = 2, heartbeat: str = "data/heartbeat") -> None:
        hb = heartbeat if os.path.isabs(heartbeat) else os.path.join(os.path.dirname(self.bb.runs.runs_dir), "heartbeat")
        lock = open(os.path.join(os.path.dirname(hb), "daemon.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # one daemon per data dir; makes orphan adoption safe
        except OSError:
            raise SystemExit("another daemon holds data/daemon.lock")
        self.adopt_orphans()
        self.bb.resume_stale()
        tg.start(self)
        last_recover = 0.0
        last_watch = 0.0
        while True:
            self.tick(max_parallel)
            if time.time() - last_recover > 60:
                self.bb.resume_stale()
                last_recover = time.time()
            every = self.bb.cfg.get("watch", {}).get("every_s", 0)
            if every and time.time() - last_watch > every:
                last_watch = time.time()
                try:
                    self.bb.watch_once()
                except Exception:
                    pass
            with open(hb, "w") as f:
                f.write(time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
            time.sleep(poll_s)
