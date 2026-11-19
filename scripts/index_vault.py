#!/usr/bin/env python3
"""Local indexer for agent-router — stdlib only (no installs).

Builds a SQLite FTS5 + TF-IDF cosine-similarity index over:
- SKILL.md files (~/.agent-skills, ~/.claude/skills)
- Hooks (~/.claude/hooks/*.py)
- Vault pages (~/memory-vault/pages/*.md)
- Local repos (~/Developer/* AGENTS.md / CLAUDE.md / README.md)
- last30days output (~/memory-vault/pages/research-*.md, last30days skill)

Output: config/index.db (SQLite, FTS5 virtual table + tfidf metadata)
Usable by the supervisor for index-aware routing before dispatch.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
INDEX_DB = os.path.join(CONFIG_DIR, "index.db")
INVENTORY_PATH = os.path.join(CONFIG_DIR, "discovered-inventory.json")

TOKEN_RE = re.compile(r"[A-Za-z0-9_/-]{3,}")


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


def discover_corpus() -> List[Dict[str, str]]:
    """Return list of {id, path, kind, text} documents to index."""
    docs: List[Dict[str, str]] = []

    # 1. SKILL.md files
    for root in (os.path.join(HOME, ".agent-skills"), os.path.join(HOME, ".claude", "skills")):
        if not os.path.isdir(root):
            continue
        for sf in glob.glob(os.path.join(root, "**", "SKILL.md"), recursive=True):
            try:
                text = Path(sf).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append({
                "id": f"skill:{sf}",
                "path": sf,
                "kind": "skill",
                "text": text,
            })

    # 2. Hooks
    hooks_dir = os.path.join(HOME, ".claude", "hooks")
    if os.path.isdir(hooks_dir):
        for hf in glob.glob(os.path.join(hooks_dir, "*.py")):
            try:
                text = Path(hf).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append({
                "id": f"hook:{hf}",
                "path": hf,
                "kind": "hook",
                "text": text,
            })

    # 3. Vault pages
    vault_pages = os.path.join(HOME, "memory-vault", "pages")
    if os.path.isdir(vault_pages):
        for pf in glob.glob(os.path.join(vault_pages, "**", "*.md"), recursive=True):
            try:
                text = Path(pf).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append({
                "id": f"vault:{pf}",
                "path": pf,
                "kind": "vault",
                "text": text,
            })

    # 4. Local repo marker files
    for root in (os.path.join(HOME, "Developer"), os.path.join(HOME, "Documents", "Acore", "Development")):
        if not os.path.isdir(root):
            continue
        for marker in ("AGENTS.md", "CLAUDE.md", "README.md"):
            for mf in glob.glob(os.path.join(root, "**", marker), recursive=True):
                try:
                    text = Path(mf).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                docs.append({
                    "id": f"repo:{mf}",
                    "path": mf,
                    "kind": "repo",
                    "text": text,
                })

    # 5. last30days research notes
    last30 = os.path.join(HOME, "Developer", "refs", "mvanhorn_last30days-skill")
    if os.path.isdir(last30):
        for lf in glob.glob(os.path.join(last30, "**", "*.md"), recursive=True):
            try:
                text = Path(lf).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append({
                "id": f"last30:{lf}",
                "path": lf,
                "kind": "last30",
                "text": text,
            })

    return docs


def build_index(docs: List[Dict[str, str]]) -> Dict[str, Any]:
    if os.path.exists(INDEX_DB):
        os.remove(INDEX_DB)
    conn = sqlite3.connect(INDEX_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(id, path, kind, text)")
    conn.executemany("INSERT INTO fts(id, path, kind, text) VALUES (?, ?, ?, ?)",
                     [(d["id"], d["path"], d["kind"], d["text"]) for d in docs])

    # TF-IDF metadata: per-doc term counts + doc frequency
    doc_terms: Dict[str, Dict[str, int]] = {}
    doc_freq: Dict[str, int] = {}
    for d in docs:
        toks = tokenize(d["text"])
        counts: Dict[str, int] = {}
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
        doc_terms[d["id"]] = counts
        for t in set(counts):
            doc_freq[t] = doc_freq.get(t, 0) + 1

    n_docs = len(docs)
    conn.execute("CREATE TABLE IF NOT EXISTS tfidf_meta (doc_id TEXT PRIMARY KEY, doc_len INT, terms JSON)")
    conn.execute("CREATE TABLE IF NOT EXISTS idf (term TEXT PRIMARY KEY, idf REAL)")
    for did, counts in doc_terms.items():
        conn.execute("INSERT OR REPLACE INTO tfidf_meta(doc_id, doc_len, terms) VALUES (?, ?, ?)",
                     (did, sum(counts.values()), json.dumps(counts)))
    for term, df in doc_freq.items():
        idf = math.log((n_docs + 1) / (df + 1)) + 1.0
        conn.execute("INSERT OR REPLACE INTO idf(term, idf) VALUES (?, ?)", (term, idf))

    conn.commit()
    conn.close()
    return {
        "indexed_docs": n_docs,
        "index_path": INDEX_DB,
        "kinds": {k: sum(1 for d in docs if d["kind"] == k) for k in set(d["kind"] for d in docs)},
    }


def search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """Hybrid search: FTS5 keyword + TF-IDF cosine similarity, merged by score."""
    conn = sqlite3.connect(INDEX_DB)
    toks = tokenize(query)
    if not toks:
        conn.close()
        return []

    # FTS5 keyword matches
    fts_rows: List[Tuple] = []
    try:
        q = " OR ".join(toks)
        fts_rows = conn.execute(
            "SELECT id, path, kind, bm25(fts) AS score FROM fts WHERE fts MATCH ? ORDER BY score LIMIT ?",
            (q, top_k * 2),
        ).fetchall()
    except sqlite3.OperationalError:
        pass

    # TF-IDF cosine similarity
    q_counts: Dict[str, int] = {}
    for t in toks:
        q_counts[t] = q_counts.get(t, 0) + 1
    q_idf: Dict[str, float] = {}
    q_norm_sq = 0.0
    rows = conn.execute("SELECT term, idf FROM idf").fetchall()
    idf_map = {t: v for t, v in rows}
    meta_rows = conn.execute("SELECT doc_id, doc_len, terms FROM tfidf_meta").fetchall()
    meta = {r[0]: (r[1], json.loads(r[2])) for r in meta_rows}

    q_vec: Dict[str, float] = {}
    for t, c in q_counts.items():
        q_vec[t] = c * idf_map.get(t, 1.0)
        q_norm_sq += q_vec[t] ** 2
    q_norm = math.sqrt(q_norm_sq) if q_norm_sq > 0 else 1.0

    sim: Dict[str, float] = {}
    for did, (doc_len, terms) in meta.items():
        dot = 0.0
        doc_norm_sq = 0.0
        for t, c in terms.items():
            w = c * idf_map.get(t, 1.0)
            doc_norm_sq += w ** 2
            if t in q_vec:
                dot += q_vec[t] * w
        doc_norm = math.sqrt(doc_norm_sq) if doc_norm_sq > 0 else 1.0
        sim[did] = dot / (q_norm * doc_norm) if (q_norm * doc_norm) > 0 else 0.0

    # Merge: FTS rank + TF-IDF sim
    fts_scores = {r[0]: 1.0 / (i + 1) for i, r in enumerate(fts_rows)}
    fts_map = {r[0]: {"path": r[1], "kind": r[2]} for r in fts_rows}
    combined: Dict[str, float] = {}
    for did in set(list(fts_scores.keys()) + list(sim.keys())):
        combined[did] = 0.6 * fts_scores.get(did, 0.0) + 0.4 * sim.get(did, 0.0)

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:top_k]
    results: List[Dict[str, Any]] = []
    for did, score in ranked:
        fm = fts_map.get(did, {"path": "", "kind": ""})
        results.append({"id": did, "path": fm["path"], "kind": fm["kind"], "score": round(score, 4)})

    conn.close()
    return results


def main() -> int:
    docs = discover_corpus()
    info = build_index(docs)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
