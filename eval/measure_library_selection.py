"""Measure library skill/command selection accuracy against silver labels.

For each heldout_v2 prompt, run library.search (hybrid FTS5) and check if the
silver-labeled skill/command appears in the top-k results.

Usage: python3 eval/measure_library_selection.py [eval/heldout_v2]
"""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backbone.db import connect
from backbone import library


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

    # Build an in-memory library from catalog.json (the silver-labeled skill names)
    con = connect(":memory:")
    cat = json.load(open(f"{d}/judge/catalog.json"))
    names = set()
    for c in cat:
        library.upsert(con, c["kind"], c["name"], c["desc"], c.get("body", ""),
                       meta={}, source="catalog")
        names.add(c["name"])

    n = t1 = t3 = n_no_hit = 0
    label_hits = Counter()
    label_total = Counter()
    misses = []

    for s in silver:
        prompt = rows[s["id"]]["prompt"]
        expected = s["silver"]
        label_total[expected] += 1
        n += 1
        hits = library.search(con, prompt, k=10)
        hit_names = [h["name"] for h in hits]
        in_top1 = hit_names[0] == expected if hit_names else False
        in_top3 = expected in hit_names[:3]
        if in_top1:
            t1 += 1
            label_hits[expected] += 1
        if in_top3:
            t3 += 1
        if not in_top1:
            misses.append({"id": s["id"], "expected": expected,
                           "top3": hit_names[:3], "prompt": prompt[:70]})

    total = max(1, n)
    out = {
        "n": n,
        "library_top1": round(t1 / total, 3),
        "library_top3": round(t3 / total, 3),
        "no_hit_rate": round(n_no_hit / total, 3),
        "catalog_size": len(names),
    }
    print(json.dumps(out, indent=2))
    print("\n--- top misses (expected vs library top3) ---")
    for m in misses[:40]:
        print(f"  expected={m['expected']:18} top3={m['top3']}  {m['prompt']}")
    if len(misses) > 40:
        print(f"  ... and {len(misses)-40} more misses")


if __name__ == "__main__":
    main()
