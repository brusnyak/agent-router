"""Retrieval eval: labeled queries -> expected skill. Prints top1/top3 per method. Exit 1 below threshold."""
from __future__ import annotations

import sys

import yaml

from . import library
from .core import Backbone
from .rerank import rerank


def run(bb: Backbone, path: str = "config/eval_queries.yaml", k: int = 3) -> dict:
    qs = yaml.safe_load(open(path))
    names = {r["name"] for r in bb.con.execute("SELECT name FROM library WHERE kind='skill'")}
    qs = [q for q in qs if q["want"] in names]
    res = {m: [0, 0] for m in ("bm25", "hybrid", "hybrid+rerank")}
    for q in qs:
        bm = [h["name"] for h in library.search(bb.con, q["q"], "skill", k)]
        hy = bb.rag.search(q["q"], "skill", 8)
        rr = rerank(lambda m: bb.chat(m, max_tokens=120), q["q"], hy, k=k)
        for m, names_ in (("bm25", bm), ("hybrid", [h["name"] for h in hy[:k]]), ("hybrid+rerank", [h["name"] for h in rr])):
            res[m][0] += names_[:1] == [q["want"]]
            res[m][1] += q["want"] in names_[:k]
    n = len(qs)
    return {"n": n, **{m: {"top1": round(v[0] / n, 2), "top3": round(v[1] / n, 2)} for m, v in res.items()}}


if __name__ == "__main__":
    out = run(Backbone())
    print(out)
    sys.exit(0 if out["hybrid+rerank"]["top3"] >= 0.8 else 1)
