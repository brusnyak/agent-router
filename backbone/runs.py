"""Durable run table: lease + heartbeat, step log, stale-run recovery, vault-style tickets."""
from __future__ import annotations

from .db import DB

import json
import os
import sqlite3
import time
import uuid
from typing import List, Optional

LEASE_S = 90


class StaleLease(RuntimeError):
    """A worker wrote to a run whose lease was reaped (fence moved on): its write is rejected."""


class Runs:
    def __init__(self, con: sqlite3.Connection, tickets_dir: str, runs_dir: str):
        self.con = con
        self.tickets_dir = os.path.expanduser(tickets_dir)
        self.runs_dir = os.path.expanduser(runs_dir)

    def create(self, session_id: str, project: str, command: str, prompt: str, worker: str, meta: Optional[dict] = None,
               rid: Optional[str] = None) -> str:
        rid = rid or uuid.uuid4().hex[:8]
        now = time.time()
        self.con.execute(
            "INSERT INTO runs(id,session_id,project,command,prompt,state,worker,lease_until,created,updated,meta) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rid, session_id, project, command, prompt, "running", worker, now + LEASE_S, now, now, json.dumps(meta or {})))
        self.con.commit()
        return rid

    def fence(self, rid: str) -> int:
        r = self.con.execute("SELECT fence FROM runs WHERE id=?", (rid,)).fetchone()
        return int(r["fence"] or 0) if r else 0

    def heartbeat(self, rid: str, fence: Optional[int] = None) -> bool:
        """Extend the lease. With a fence, a reaped run (fence moved on) is not revived: returns False."""
        now = time.time()
        q, a = "UPDATE runs SET lease_until=?, updated=? WHERE id=?", [now + LEASE_S, now, rid]
        if fence is not None:
            q += " AND fence=?"; a.append(fence)
        n = self.con.execute(q, tuple(a)).rowcount
        self.con.commit()
        return n > 0

    def reap(self, rid: str, reason: str) -> bool:
        """Declare an expired run dead and bump the fence so the zombie's later writes are rejected."""
        n = self.con.execute("UPDATE runs SET state='blocked', error=?, fence=fence+1, updated=? WHERE id=? AND state='running'",
                             (reason[:2000], time.time(), rid)).rowcount
        self.con.commit()
        return n > 0

    def step(self, rid: str, n: int, kind: str, worker: str, key_slot: str, ok: bool, latency_ms: int,
             output: str, note: str = "", fence: Optional[int] = None) -> None:
        if fence is not None and fence != self.fence(rid):
            raise StaleLease(f"run {rid}: lease was reaped (fence {fence} != {self.fence(rid)}); step rejected")
        self.con.execute("INSERT INTO steps(run_id,n,kind,worker,key_slot,ok,latency_ms,output,note,ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (rid, n, kind, worker, key_slot, int(ok), latency_ms, output[:20000], note, time.time()))
        self.con.commit()
        self.heartbeat(rid, fence)

    def set(self, rid: str, state: str, error: str = "", worker: Optional[str] = None, attempt: Optional[int] = None,
            fence: Optional[int] = None) -> bool:
        sets, args = ["state=?", "error=?", "updated=?"], [state, error[:2000], time.time()]
        if worker is not None:
            sets.append("worker=?"); args.append(worker)
        if attempt is not None:
            sets.append("attempt=?"); args.append(attempt)
        q = f"UPDATE runs SET {', '.join(sets)} WHERE id=?"
        if fence is not None:  # fenced write: only the owner of the current epoch may change the run
            q += " AND fence=?"; args = [*args, rid, fence]
        else:
            args = [*args, rid]
        n = self.con.execute(q, tuple(args)).rowcount
        self.con.commit()
        return n > 0

    def get(self, rid: str) -> Optional[dict]:
        r = self.con.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        return dict(r) if r else None

    def steps(self, rid: str) -> List[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM steps WHERE run_id=? ORDER BY id", (rid,))]

    def list(self, limit: int = 20) -> List[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id,state,command,worker,attempt,substr(prompt,1,60) AS prompt,updated FROM runs ORDER BY updated DESC LIMIT ?", (limit,))]

    def stale(self) -> List[dict]:
        """Runs still marked running whose lease expired: the process died. Safe to retry."""
        return [dict(r) for r in self.con.execute(
            "SELECT * FROM runs WHERE state='running' AND lease_until < ?", (time.time(),))]

    def ticket(self, rid: str, reason: str, strategy: str) -> str:
        run = self.get(rid) or {}
        os.makedirs(self.tickets_dir, exist_ok=True)
        path = os.path.join(self.tickets_dir, f"{time.strftime('%Y-%m-%d')}-run-{rid}.md")
        last = self.steps(rid)[-3:]
        body = (f"---\ntype: ticket\nstatus: blocked\nrun: {rid}\nworker: {run.get('worker')}\n"
                f"attempts: {run.get('attempt')}\ncreated: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n---\n"
                f"# Run {rid} needs a different approach\n\n**Task:** {run.get('prompt', '')[:500]}\n\n"
                f"**Why it stopped:** {reason}\n\n**Next strategy:** {strategy}\n\n## Last steps\n" +
                "\n".join(f"- step {s['n']} {s['kind']} on {s['worker']}: ok={bool(s['ok'])} {s['output'][:200]!r}" for s in last) + "\n")
        with open(path, "w") as f:
            f.write(body)
        self.con.execute("UPDATE runs SET ticket=? WHERE id=?", (path, rid))
        self.con.commit()
        return path

    def save_patch(self, rid: str, diff: str) -> str:
        d = os.path.join(self.runs_dir, rid)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "patch.diff")
        with open(p, "w") as f:
            f.write(diff)
        return p
