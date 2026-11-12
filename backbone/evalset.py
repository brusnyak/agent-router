"""Retrieval eval: labeled queries -> expected skill. Prints top1/top3 per method. Exit 1 below threshold."""
from __future__ import annotations

import sys

import yaml

from . import library
from .core import Backbone
from .rerank import rerank


def run(bb: Backbone, path: str = "config/eval_queries.yaml", k: int = 3) -> dict:
    qs = yaml.safe_load(open(path))
    have = {(r["kind"], r["name"]) for r in bb.con.execute("SELECT kind, name FROM library")}
    for q in qs:
        q["want"] = q["want"] if isinstance(q["want"], list) else [q["want"]]
    qs = [q for q in qs if any((q.get("kind", "skill"), w) in have for w in q["want"])]
    res = {m: [0, 0] for m in ("bm25", "hybrid", "hybrid+rerank", "expand", "expand+reason")}
    from . import understand
    big = lambda m: bb.chat(m, max_tokens=500)
    for q in qs:
        kd = q.get("kind", "skill")
        bm = [h["name"] for h in library.search(bb.con, q["q"], kd, k)]
        hy = bb.rag.search(q["q"], kd, 8)
        rr = rerank(lambda m: bb.chat(m, max_tokens=120), q["q"], hy, k=k)
        ex = understand.expand(big, q["q"])
        hx = bb.rag.search(q["q"] + " " + ex, kd, 10)
        rx = understand.rerank(big, q["q"], hx, k=k)
        for m, names_ in (("bm25", bm), ("hybrid", [h["name"] for h in hy[:k]]), ("hybrid+rerank", [h["name"] for h in rr]),
                          ("expand", [h["name"] for h in hx[:k]]), ("expand+reason", [h["name"] for h in rx[:k]])):
            res[m][0] += bool(names_[:1]) and names_[0] in q["want"]
            res[m][1] += any(w in names_[:k] for w in q["want"])
    n = len(qs)
    return {"n": n, **{m: {"top1": round(v[0] / n, 2), "top3": round(v[1] / n, 2)} for m, v in res.items()}}


if __name__ == "__main__":
    out = run(Backbone())
    print(out)
    sys.exit(0 if max(v["top3"] for v in out.values() if isinstance(v, dict)) >= 0.9 else 1)
