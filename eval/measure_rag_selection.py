"""Measure rag.search (hybrid BM25+dense NIM) skill selection accuracy vs silver labels.
Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/measure_rag_selection.py [eval/heldout_v2]
"""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backbone.db import connect
from backbone.rag import Rag
from backbone.keys import KeyPool


def load(d):
    rows = {}
    for f in ("dev", "test"):
        for l in open(f"{d}/{f}.jsonl"):
            r = json.loads(l)
            rows[r["id"]] = r
    silver = [json.loads(l) for l in open(f"{d}/silver.jsonl")]
    return rows, silver


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
    rows, silver = load(d)


    con = connect(":memory:")
    cat = json.load(open(f"{d}/judge/catalog.json"))
    names = set()
    for c in cat:
        from backbone import library as L
        L.upsert(con, c["kind"], c["name"], c["desc"], c.get("body", ""),
                 meta={}, source="catalog")
        names.add(c["name"])

    keys = [k for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
    pool = KeyPool(keys) if keys else KeyPool([], env={})
    rag = Rag(con, pool, {"base_url": "https://integrate.api.nvidia.com/v1",
                          "embed_model": "nvidia/nemotron-3.5-embed-1b"})
    # embed catalog
    rag.embed_missing(limit=2000)

    n = t1 = t3 = 0
    misses = []
    for s in silver:
        prompt = rows[s["id"]]["prompt"]
        expected = s["silver"]
        n += 1
        hits = rag.search(prompt, k=10)
        hit_names = [h["name"] for h in hits]
        if hit_names[:1] == [expected]:
            t1 += 1
        if expected in hit_names[:3]:
            t3 += 1
        if hit_names[:1] != [expected]:
            misses.append({"expected": expected, "top3": hit_names[:3], "prompt": prompt[:60]})

    total = max(1, n)
    print(json.dumps({
        "n": n,
        "rag_hybrid_top1": round(t1 / total, 3),
        "rag_hybrid_top3": round(t3 / total, 3),
        "majority_floor": round(max(Counter(s['silver'] for s in silver).values()) / total, 3),
    }, indent=2))
    print("\n--- top misses ---")
    for m in misses[:30]:
        print(f"  expected={m['expected']:18} top3={m['top3']}  {m['prompt']}")


if __name__ == "__main__":
    main()
