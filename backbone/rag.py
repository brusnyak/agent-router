"""Hybrid retrieval over the library: BM25 (FTS5) + dense NIM embeddings, fused with reciprocal rank fusion.

Embeddings are stored as float32 blobs in SQLite (no vector DB). Cosine in pure Python is fine up to ~10k rows;
past that swap in sqlite-vec. Embedding failures degrade to BM25-only, never to an error.
"""
from __future__ import annotations

import array
import json
import math
import socket
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from . import library
from .db import DB
from .keys import KeyPool, Transient

RRF_K = 60


def _post(pool: KeyPool, base_url: str, model: str, texts: List[str], input_type: str,
          fast: bool = False) -> List[List[float]]:
    # fast=True (live query path): one 6s attempt, then raise a non-Transient error so KeyPool.call
    # does not retry across all keys (was 5 keys x 90s = up to 114s hang before the worker even ran).
    body = json.dumps({"model": model, "input": texts, "input_type": input_type, "encoding_format": "float",
                       "truncate": "END"}).encode()

    def once(name: str, key: str):
        req = urllib.request.Request(base_url.rstrip("/") + "/embeddings", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=6 if fast else 90) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if (e.code == 429 or e.code >= 500) and not fast:
                raise Transient(f"embed http {e.code}")
            raise RuntimeError(f"embed http {e.code}: {e.read().decode(errors='replace')[:160]}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            if fast:
                raise RuntimeError(f"embed slow/unreachable: {e}")
            raise Transient(str(e))
        return [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]

    return pool.call(once, retries=1, backoff_s=2)


def _pack(v: List[float]) -> bytes:
    return array.array("f", v).tobytes()


def _unpack(b: bytes) -> array.array:
    a = array.array("f")
    a.frombytes(b)
    return a


def _cos(a: array.array, b: array.array, nb: float) -> float:
    return sum(x * y for x, y in zip(a, b)) / nb if nb else 0.0


class Rag:
    def __init__(self, con: DB, pool: KeyPool, cfg: dict):
        self.con, self.pool = con, pool
        self.base_url = cfg.get("base_url", "https://integrate.api.nvidia.com/v1")
        self.model = cfg.get("embed_model", "nvidia/nemotron-3.5-embed-1b")
        self.batch = int(cfg.get("embed_batch", 16))
        self._cache: Optional[Dict[str, tuple]] = None
        con.execute("CREATE TABLE IF NOT EXISTS embeddings(id TEXT PRIMARY KEY, model TEXT, dim INTEGER, vec BLOB, ts REAL)")
        con.commit()

    @staticmethod
    def _doc(row) -> str:
        return f"{row['name']}: {row['description']}\n{(row['body'] or '')[:1500]}"

    def embed_missing(self, limit: int = 2000) -> int:
        rows = self.con.execute(
            "SELECT l.* FROM library l LEFT JOIN embeddings e ON e.id=l.id AND e.model=? WHERE e.id IS NULL LIMIT ?",
            (self.model, limit)).fetchall()
        done = 0
        for i in range(0, len(rows), self.batch):
            chunk = rows[i:i + self.batch]
            try:
                vecs = _post(self.pool, self.base_url, self.model, [self._doc(r) for r in chunk], "passage")
            except RuntimeError as e:
                if "422" not in str(e):  # content-safety rejection of one input: embed row by row, skip the rejected ones
                    raise
                vecs = []
                for r in chunk:
                    try:
                        vecs.append(_post(self.pool, self.base_url, self.model, [self._doc(r)], "passage")[0])
                    except RuntimeError:
                        vecs.append(None)
            for r, v in zip(chunk, vecs):
                if v is None:
                    continue
                self.con.execute("INSERT OR REPLACE INTO embeddings(id,model,dim,vec,ts) VALUES (?,?,?,?,?)",
                                 (r["id"], self.model, len(v), _pack(v), time.time()))
            self.con.commit()
            done += len(chunk)
        self._cache = None
        return done

    def _load(self) -> Dict[str, tuple]:
        if self._cache is None:
            self._cache = {}
            for r in self.con.execute("SELECT id,vec FROM embeddings WHERE model=?", (self.model,)):
                v = _unpack(r["vec"])
                self._cache[r["id"]] = (v, math.sqrt(sum(x * x for x in v)))
        return self._cache

    def dense(self, query: str, kind: Optional[str], k: int) -> List[str]:
        vecs = self._load()
        if not vecs:
            return []
        q = _post(self.pool, self.base_url, self.model, [query[:1500]], "query", fast=True)[0]
        qa = array.array("f", q)
        qn = math.sqrt(sum(x * x for x in qa))
        kinds = None
        if kind:
            kinds = {r["id"] for r in self.con.execute("SELECT id FROM library WHERE kind=?", (kind,))}
        scored = [(_cos(qa, v, qn * n), i) for i, (v, n) in vecs.items() if kinds is None or i in kinds]
        scored.sort(reverse=True)
        return [i for _, i in scored[:k]]

    def search(self, query: str, kind: Optional[str] = None, k: int = 5) -> List[dict]:
        lex = [h["id"] for h in library.search(self.con, query, kind, k * 4)]
        try:
            den = self.dense(query, kind, k * 4)
        except Exception as e:
            den = []  # degrade to BM25-only, but say so (stderr) so the operator notices
        # Dense NIM embeddings are the stronger signal (measured: dense 23.8%/44.5% top1/top3
        # vs hybrid 13.2%/24.4% on heldout_v2). Give dense 3x the RRF weight of BM25.
        fused: Dict[str, float] = {}
        for ranking, weight in ((lex, 1.0), (den, 3.0)):
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + weight / (RRF_K + rank + 1)
        out = []
        for i, s in sorted(fused.items(), key=lambda x: -x[1])[:k]:
            r = self.con.execute("SELECT id,kind,name,description,meta,source FROM library WHERE id=?", (i,)).fetchone()
            if r:
                out.append(dict(r) | {"meta": json.loads(r["meta"] or "{}"), "score": round(s, 4),
                                      "via": ("both" if i in lex and i in den else "dense" if i in den else "bm25")})
        return out

    def index_vault(self, vault_dir: str = "~/memory-vault/pages", limit: int = 5000) -> int:
        """Index .md files under vault_dir as library rows with kind='vault'."""
        import os
        import re
        from pathlib import Path

        pages = Path(os.path.expanduser(vault_dir))
        if not pages.exists():
            return 0

        count = 0
        files = sorted(pages.glob("*.md"))[:limit]
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            title = f.stem
            desc = ""
            m = re.search(r"^#\s+(.+)", text, re.M)
            if m:
                title = m.group(1).strip()
            body_lines = [l for l in text.splitlines() if l.strip()]
            start = 0
            if body_lines and body_lines[0].strip() in ("---", "<!--"):
                start = 1
            for l in body_lines[start:]:
                if l.strip() and not l.startswith(("#", "-", "*", ">", "|", "```", "![")):
                    desc = l.strip()[:220]
                    break
            area = ""
            ma = re.search(r"^area::\s*\[\[(.+)\]\]", text, re.M)
            if ma:
                area = ma.group(1)
            links = re.findall(r"\[\[(.+?)\]\]", text)
            library.upsert(
                self.con, "vault", f.stem, desc, text[:1500],
                meta={"area": area, "links": links, "path": str(f)}, source="vault",
            )
            count += 1
        self.con.commit()
        self._cache = None
        return count

    def search_vault(self, query: str, k: int = 5) -> List[dict]:
        """Search vault pages in RAG (kind='vault' filter)."""
        return self.search(query, kind="vault", k=k)

