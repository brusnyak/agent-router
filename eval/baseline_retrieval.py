"""No-LLM retrieval baseline vs silver labels. stdlib TF-IDF over catalog descriptions.
Usage: python3 eval/baseline_retrieval.py [eval/heldout_v2]. Reports top1/top3 per split and a majority-label floor."""
import json, math, re, sys
from collections import Counter

d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
norm = lambda s: str(s).strip().strip("\"'")
tok = lambda t: re.findall(r"[a-z][a-z0-9]{2,}", t.lower())
cat = {norm(c["name"]): c["name"] + " " + c["desc"] for c in json.load(open(f"{d}/judge/catalog.json"))}
docs = {n: Counter(tok(t)) for n, t in cat.items()}
df = Counter(w for c in docs.values() for w in c)
idf = {w: math.log(1 + len(docs) / df[w]) for w in df}
norms = {n: math.sqrt(sum((c[w] * idf[w]) ** 2 for w in c)) or 1 for n, c in docs.items()}


def rank(prompt):
    q = Counter(tok(prompt))
    sc = {n: sum(q[w] * idf.get(w, 0) * c[w] * idf[w] for w in q if w in c) / norms[n] for n, c in docs.items()}
    return [n for n, s in sorted(sc.items(), key=lambda x: -x[1]) if s > 0]


rows = {}
for f in ("dev", "test"):
    for l in open(f"{d}/{f}.jsonl"):
        r = json.loads(l)
        rows[r["id"]] = r
silver = [json.loads(l) for l in open(f"{d}/silver.jsonl")]
major = Counter(s["silver"] for s in silver).most_common(1)[0][0]
out = {"majority_label": major}
for split in ("dev", "test", "all"):
    ss = [s for s in silver if split == "all" or s["split"] == split]
    t1 = t3 = m = 0
    for s in ss:
        top = rank(rows[s["id"]]["prompt"])
        t1 += bool(top) and top[0] == s["silver"]
        t3 += s["silver"] in top[:3]
        m += s["silver"] == major
    n = max(1, len(ss))
    out[split] = {"n": len(ss), "top1": round(t1 / n, 3), "top3": round(t3 / n, 3), "majority_floor": round(m / n, 3)}
print(json.dumps(out))
