"""Session memory and context packing.

Honest scope: this does not enlarge a model's window. It keeps every turn on disk, folds old turns into a
rolling summary, retrieves older turns and vault pages by relevance, and packs the prompt under a token budget
in priority order: pinned facts > summary > retrieved > recent turns.
"""
from __future__ import annotations

from .db import DB

from .paths import vault_dir

import os
import re
import sqlite3
import subprocess
import time
import uuid
from typing import Callable, List, Optional


def est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _clip(text: str, tokens: int) -> str:
    return text if est_tokens(text) <= tokens else text[: tokens * 4] + " ...[clipped]"


class Sessions:
    def __init__(self, con: sqlite3.Connection, cfg: dict):
        self.con = con
        self.budget = int(cfg.get("budget_tokens", 24000))
        self.fold_over = int(cfg.get("summarize_over_tokens", 12000))
        self.keep_recent = int(cfg.get("keep_recent_turns", 6))
        self.vault_query = os.path.expanduser(cfg.get("vault_query") or vault_dir("scripts", "vector_memory", "query.py"))

    def open(self, session_id: Optional[str] = None, project: str = "") -> str:
        sid = session_id or uuid.uuid4().hex[:10]
        self.con.execute("INSERT OR IGNORE INTO sessions(id,project,created) VALUES (?,?,?)", (sid, project, time.time()))
        self.con.commit()
        return sid

    def add_turn(self, sid: str, role: str, text: str) -> int:
        cur = self.con.execute("INSERT INTO turns(session_id,role,text,tokens,ts) VALUES (?,?,?,?,?)",
                               (sid, role, text, est_tokens(text), time.time()))
        self.con.commit()
        return cur.lastrowid

    def _summary(self, sid: str):
        return self.con.execute("SELECT * FROM summaries WHERE session_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()

    def _unfolded(self, sid: str) -> List[sqlite3.Row]:
        s = self._summary(sid)
        after = s["upto_turn"] if s else 0
        return self.con.execute("SELECT * FROM turns WHERE session_id=? AND id>? ORDER BY id", (sid, after)).fetchall()

    def maybe_fold(self, sid: str, summarize: Callable[[str], str]) -> bool:
        """Fold turns older than the last `keep_recent` into the rolling summary once they exceed the threshold."""
        turns = self._unfolded(sid)
        if sum(t["tokens"] for t in turns) <= self.fold_over or len(turns) <= self.keep_recent:
            return False
        old = turns[: -self.keep_recent]
        prev = self._summary(sid)
        text = ("Existing summary:\n" + prev["text"] + "\n\n" if prev else "") + "New turns:\n" + "\n".join(
            f"[{t['role']}] {t['text']}" for t in old)
        new = summarize("Fold this into one compact running summary. Keep decisions, file paths, commands, open "
                        "questions and owner constraints; drop chatter.\n\n" + _clip(text, 9000))
        self.con.execute("INSERT INTO summaries(session_id,upto_turn,text,ts) VALUES (?,?,?,?)",
                         (sid, old[-1]["id"], new, time.time()))
        self.con.commit()
        return True

    def recall(self, sid: str, query: str, k: int = 3) -> List[str]:
        words = re.findall(r"[A-Za-z0-9_]{3,}", query.lower())[:10]
        if not words:
            return []
        fq = " OR ".join(f'"{w}"' for w in words)
        try:
            rows = self.con.execute(
                "SELECT t.role,t.text FROM turns_fts JOIN turns t ON t.id=turns_fts.rowid "
                "WHERE turns_fts MATCH ? AND t.session_id=? ORDER BY bm25(turns_fts) LIMIT ?", (fq, sid, k)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [f"[{r['role']}] {_clip(r['text'], 300)}" for r in rows]

    def vault(self, query: str, k: int = 3) -> List[str]:
        if not os.path.exists(self.vault_query):
            return []
        try:
            p = subprocess.run(["python3", self.vault_query, query[:300], "--top-k", str(k)], capture_output=True,
                               text=True, timeout=15, stdin=subprocess.DEVNULL)
        except Exception:
            return []
        return [ln[:240] for ln in p.stdout.splitlines() if ln.startswith("[")][:k]

    def pack(self, sid: str, task: str, pinned: str = "", library_notes: str = "", use_vault: bool = True,
             project: Optional[str] = None) -> str:
        """Assemble the prompt context under budget. Priority order, each section clipped to its share."""
        anchors = ""
        if use_vault:
            try:
                # The graph stores core.run's resolved project on the session.
                if project is None:
                    row = self.con.execute("SELECT project FROM sessions WHERE id=?", (sid,)).fetchone()
                    project = row["project"] if row else ""
                if project:
                    from .retrieval import Registry, load_yaml

                    registry = Registry()
                    projects = load_yaml(registry.projects_path).get("projects", [])
                    if any(p.get("id") == project and p.get("anchors") for p in projects):
                        anchors = (registry.context_pack(task, project) or "")[:6000]
            except Exception:
                pass  # Retrieval is optional; retain the existing vault fallback.
        parts: List[str] = []
        left = self.budget - est_tokens(task)
        if anchors:
            parts.append("## PROJECT ANCHORS + RECALL (sources shown; vault wins on conflict)\n" + anchors)
        if pinned:
            parts.append("## Pinned\n" + _clip(pinned, min(2000, left // 6)))
        if library_notes:
            parts.append("## Relevant library\n" + _clip(library_notes, min(1500, left // 8)))
        s = self._summary(sid)
        if s:
            parts.append("## Session summary\n" + _clip(s["text"], left // 4))
        retrieved = self.recall(sid, task) + (self.vault(task) if use_vault and not anchors else [])
        if retrieved:
            parts.append("## Retrieved\n" + "\n".join(retrieved))
        used = sum(est_tokens(p) for p in parts)
        recent = self._unfolded(sid)[-self.keep_recent:]
        room = max(0, left - used)
        lines: List[str] = []
        for t in reversed(recent):
            ln = f"[{t['role']}] {t['text']}"
            if est_tokens(ln) > room:
                ln = _clip(ln, room) if room > 200 else ""
            if not ln:
                break
            lines.append(ln)
            room -= est_tokens(ln)
        if lines:
            parts.append("## Recent turns\n" + "\n".join(reversed(lines)))
        # enforce the budget: drop lowest-priority sections first (recent turns, retrieved), then clip the task
        task_part = "## Task\n" + task
        while parts and est_tokens("\n\n".join(parts + [task_part])) > self.budget:
            parts.pop()  # last appended = lowest priority
        packed = "\n\n".join(parts + [task_part])
        if est_tokens(packed) > self.budget:
            packed = packed[: self.budget * 4] + "\n...[task clipped to budget]"
        return packed
