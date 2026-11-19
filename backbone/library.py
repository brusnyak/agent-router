"""Library: commands, prompts, skills, personas as rows. Ingest from markdown, search with FTS5.

Everything the router can be told to use (slash commands, prompt templates, skills) lives here
as data, so adding the 80th command is an ingest, not a code change.
"""
from __future__ import annotations

from .db import DB

import hashlib
import json
import os
import re
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional

_FM = re.compile(r"^(?:---|<!--)\s*\n(.*?)\n(?:---|-->)\s*\n?", re.S)  # YAML-style or HTML-comment front matter


def parse_markdown(text: str) -> tuple[Dict[str, Any], str]:
    """Tiny frontmatter parser: `key: value` lines and `key: >` folded blocks. No YAML dependency."""
    m = _FM.match(text)
    if not m:
        return {}, text
    meta: Dict[str, Any] = {}
    key = None
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if kv and not line.startswith(" "):
            key, val = kv.group(1), kv.group(2).strip()
            meta[key] = "" if val in (">", "|", ">-", "|-") else val.strip("\"'")
        elif key and line.strip():
            meta[key] = (str(meta.get(key, "")) + " " + line.strip()).strip()
    return meta, text[m.end():]


def item_id(kind: str, name: str, source: str) -> str:
    return kind + ":" + name + ":" + hashlib.sha1(source.encode()).hexdigest()[:6]


def upsert(con: sqlite3.Connection, kind: str, name: str, description: str, body: str,
           meta: Optional[dict] = None, source: str = "") -> str:
    iid = item_id(kind, name, source)
    con.execute(
        "INSERT INTO library(id,kind,name,description,body,meta,source,updated) VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET description=excluded.description, body=excluded.body, "
        "meta=excluded.meta, updated=excluded.updated",
        (iid, kind, name, description, body, json.dumps(meta or {}), source, time.time()),
    )
    con.commit()
    return iid


def detect_license(root: str) -> str:
    """Nearest LICENSE* file within 3 parent levels: first non-empty line, else ''. Recorded per row for the open-source audit."""
    d = os.path.abspath(root)
    for _ in range(4):
        for fn in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
            f = os.path.join(d, fn)
            if os.path.isfile(f):
                try:
                    return next((l.strip() for l in open(f, encoding="utf-8", errors="replace") if l.strip()), "")[:60]
                except OSError:
                    return ""
        d = os.path.dirname(d)
    return ""


def ingest_dir(con: sqlite3.Connection, root: str, kind: str, max_body: int = 60000, prefix: str = "", match: str = "") -> int:
    """Ingest *.md under root. Skills are <dir>/SKILL.md; commands are <name>.md. Returns rows written."""
    root = os.path.expanduser(root)
    n = 0
    if not os.path.isdir(root):
        return 0
    lic = detect_license(root)
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "references", "assets")]
        for fn in files:
            if not fn.endswith(".md") or "sync-conflict" in fn or fn.lower().startswith(("readme", "changelog", "contributing", "security", "code_of")):
                continue
            if kind == "skill" and fn != "SKILL.md":
                continue
            if prefix and not fn.startswith(prefix):
                continue
            path = os.path.join(dirpath, fn)
            if match and not re.search(match, path):
                continue
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            meta, body = parse_markdown(text)
            if lic:
                meta["license"] = lic
            name = meta.get("name") or (os.path.basename(dirpath) if fn == "SKILL.md" else fn[:-3])
            if kind in ("system", "hook") and fn != "SKILL.md":  # rules repeat per language: keep them distinguishable
                name = f"{os.path.basename(dirpath)}/{fn[:-3]}"
            desc = meta.get("description", "") or body.strip().split("\n", 1)[0][:200]
            upsert(con, kind, name, desc, body[:max_body], meta, path)
            n += 1
    return n


def _fts_query(q: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", q.lower())][:12]
    return " OR ".join(f'"{w}"' for w in words)


def search(con: sqlite3.Connection, query: str, kind: Optional[str] = None, k: int = 5) -> List[Dict[str, Any]]:
    fq = _fts_query(query)
    if not fq:
        return []
    sql = ("SELECT l.id,l.kind,l.name,l.description,l.meta,l.source,bm25(library_fts,5.0,3.0,1.0) AS score "
           "FROM library_fts JOIN library l ON l.rowid=library_fts.rowid WHERE library_fts MATCH ?")
    args: list = [fq]
    if kind:
        sql += " AND l.kind=?"
        args.append(kind)
    sql += " ORDER BY score LIMIT ?"
    args.append(k)
    try:
        rows = con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) | {"meta": json.loads(r["meta"] or "{}")} for r in rows]


def get(con: sqlite3.Connection, kind: str, name: str) -> Optional[Dict[str, Any]]:
    r = con.execute("SELECT * FROM library WHERE kind=? AND name=? ORDER BY updated DESC LIMIT 1", (kind, name)).fetchone()
    return (dict(r) | {"meta": json.loads(r["meta"] or "{}")}) if r else None


def counts(con: sqlite3.Connection) -> Dict[str, int]:
    return {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM library GROUP BY kind")}
# What the hook may route to. Personas (agent/subagent) and commands are suggested, skills are injected (see hook.py).
INDEX_KINDS = ('skill', 'agent', 'subagent', 'command')
NOT_ROUTABLE = re.compile(r'^(Agent Prompt|System Prompt|System Reminder|Tool Description|Data|Skill):', re.I)


def export_index(con: sqlite3.Connection, path: str, kinds: Optional[List[str]] = None,
                 limit_per_kind: Optional[int] = None) -> int:
    """Export a compact, hook-consumable index of library rows.

    Each row: {id, kind, name, description, body (truncated), meta}.
    Written as JSONL so the hook can load it without importing the router.
    """
    import os
    out = 0
    kinds = kinds or list(INDEX_KINDS)
    lines: List[str] = []
    seen = set()
    for kind in kinds:
        q = "SELECT id, kind, name, description, body, meta, source FROM library WHERE kind=?"
        if limit_per_kind:
            q += " ORDER BY updated DESC LIMIT ?"
            rows = con.execute(q, (kind, limit_per_kind)).fetchall()
        else:
            rows = con.execute(q, (kind,)).fetchall()
        for r in rows:
            if NOT_ROUTABLE.match(r[2] or "") or (r[1], r[2]) in seen:   # vendor system prompts; duplicate names
                continue
            seen.add((r[1], r[2]))
            row = {
                "id": r[0], "kind": r[1], "name": r[2],
                "description": r[3] or "",
                "body": (r[4] or "")[:2000],
                "meta": json.loads(r[5] or "{}"),
                "source": r[6] or "",
            }
            lines.append(json.dumps(row, ensure_ascii=False))
            out += 1
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        if lines:
            fh.write("\n")
    return out
