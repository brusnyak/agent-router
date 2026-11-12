"""SQLite storage for the backbone: library, sessions, runs. One file, WAL, FTS5."""
from __future__ import annotations

import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS library(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, description TEXT DEFAULT '',
  body TEXT DEFAULT '', meta TEXT DEFAULT '{}', source TEXT DEFAULT '', updated REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(
  name, description, body, content='library', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS library_ai AFTER INSERT ON library BEGIN
  INSERT INTO library_fts(rowid,name,description,body) VALUES (new.rowid,new.name,new.description,new.body);
END;
CREATE TRIGGER IF NOT EXISTS library_ad AFTER DELETE ON library BEGIN
  INSERT INTO library_fts(library_fts,rowid,name,description,body) VALUES ('delete',old.rowid,old.name,old.description,old.body);
END;
CREATE TRIGGER IF NOT EXISTS library_au AFTER UPDATE ON library BEGIN
  INSERT INTO library_fts(library_fts,rowid,name,description,body) VALUES ('delete',old.rowid,old.name,old.description,old.body);
  INSERT INTO library_fts(rowid,name,description,body) VALUES (new.rowid,new.name,new.description,new.body);
END;

CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, project TEXT, created REAL, title TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS turns(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
  text TEXT NOT NULL, tokens INTEGER DEFAULT 0, ts REAL
);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(text, content='turns', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
  INSERT INTO turns_fts(rowid,text) VALUES (new.id,new.text);
END;
CREATE TABLE IF NOT EXISTS summaries(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, upto_turn INTEGER NOT NULL, text TEXT NOT NULL, ts REAL
);

CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, session_id TEXT, project TEXT, command TEXT, prompt TEXT, state TEXT NOT NULL,
  worker TEXT, attempt INTEGER DEFAULT 0, lease_until REAL DEFAULT 0, error TEXT DEFAULT '',
  ticket TEXT DEFAULT '', created REAL, updated REAL, meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, text TEXT NOT NULL, opts TEXT DEFAULT '{}', state TEXT NOT NULL, owner TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0, run_id TEXT DEFAULT '', created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS steps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, n INTEGER, kind TEXT, worker TEXT, key_slot TEXT,
  ok INTEGER, latency_ms INTEGER, tokens INTEGER DEFAULT 0, output TEXT DEFAULT '', note TEXT DEFAULT '', ts REAL
);
"""

class _Result:
    def __init__(self, rows, lastrowid, rowcount=0):
        self.rows, self.lastrowid, self.rowcount = rows, lastrowid, rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class DB:
    """One connection shared by worker threads: every statement runs and is fully fetched under one lock.
    (An unlocked shared connection segfaulted Python 3.14 under parallel fan-out.)"""

    def __init__(self, con: sqlite3.Connection):
        self._c = con
        self._l = threading.RLock()

    def execute(self, sql: str, args=()):
        with self._l:
            cur = self._c.execute(sql, args)
            rows = cur.fetchall() if cur.description else []
            return _Result(rows, cur.lastrowid, cur.rowcount)

    def commit(self) -> None:
        with self._l:
            self._c.commit()


def connect(path: str) -> DB:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    return DB(con)
