"""Approval deck store: one SQLite file, stdlib only. Agents `add` cards (outreach message + lead + demo link, an application
with its exact answers, a new source, any yes/no), the owner swipes them in /approvals, senders ask `status(id)` before acting.
decision: approve | reject | later | pending. A comment travels with the decision (e.g. "approve, but shorter")."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

PATH = os.path.expanduser(os.environ.get("BACKBONE_APPROVALS_DB", "~/.agent-router/data/approvals.db"))


def _con() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    c = sqlite3.connect(PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS cards(
        id TEXT PRIMARY KEY, kind TEXT, title TEXT, body TEXT, link TEXT, meta TEXT, batch TEXT,
        decision TEXT DEFAULT 'pending', comment TEXT DEFAULT '', created REAL, decided REAL)""")
    return c


def add(kind: str, title: str, body: str, link: str = "", meta: dict | None = None, batch: str = "", card_id: str = "") -> str:
    cid = card_id or uuid.uuid4().hex[:10]
    with _con() as c:
        c.execute("INSERT OR IGNORE INTO cards(id,kind,title,body,link,meta,batch,created) VALUES(?,?,?,?,?,?,?,?)",
                  (cid, kind, title, body, link, json.dumps(meta or {}), batch, time.time()))
    return cid


def pending(limit: int = 200) -> list:
    with _con() as c:
        rows = c.execute("SELECT * FROM cards WHERE decision IN ('pending','later') ORDER BY decision='later', created LIMIT ?", (limit,))
        return [dict(r) for r in rows]


def decide(cid: str, decision: str, comment: str = "") -> bool:
    if decision not in ("approve", "reject", "later", "pending"):
        raise ValueError("decision must be approve|reject|later|pending")
    with _con() as c:
        n = c.execute("UPDATE cards SET decision=?, comment=?, decided=? WHERE id=?",
                      (decision, comment, time.time() if decision != "pending" else None, cid)).rowcount
    return bool(n)


def status(cid: str) -> dict:
    with _con() as c:
        r = c.execute("SELECT id,kind,title,decision,comment,decided FROM cards WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else {"id": cid, "decision": "unknown"}


def approved(cid: str) -> bool:
    """The only question a sender may ask. Unknown, pending, later and reject all mean no."""
    return status(cid).get("decision") == "approve"


def counts() -> dict:
    with _con() as c:
        return {r[0]: r[1] for r in c.execute("SELECT decision, COUNT(*) FROM cards GROUP BY decision")}
