"""Dense retrieval baseline vs silver labels via NIM embeddings. stdlib only.
Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/baseline_embed.py [eval/heldout_v2]
Embeds 73 catalog entries (passage) + silver prompts (query), cosine top-k. Prompt text goes to NIM (owner-approved 2026-11-13)."""
import json, math, os, sys, time, urllib.request
from collections import Counter

d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
KEYS = [os.environ[k] for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
MODEL = "nvidia/nemotron-3.5-embed-1b"
norm = lambda s: str(s).strip().strip("\"'")
calls = [0]


def embed(texts, kind):
    out = []
    for i in range(0, len(texts), 1):  # this NIM embed model returns 500 for batches >1 (measured 2026-11-13)
        body = json.dumps({"model": MODEL, "input": [t[:1500] for t in texts[i:i + 1]], "input_type": kind, "encoding_format": "float"}).encode()
        for attempt in range(4):
            calls[0] += 1
            req = urllib.request.Request("https://integrate.api.nvidia.com/v1/embeddings", body,
                                         {"Authorization": "Bearer " + KEYS[calls[0] % len(KEYS)], "Content-Type": "application/json"})
            try:
                out += [x["embedding"] for x in json.load(urllib.request.urlopen(req, timeout=120))["data"]]
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
    return out


def unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


cat = json.load(open(f"{d}/judge/catalog.json"))
names = [norm(c["name"]) for c in cat]
cv = [unit(v) for v in embed([c["name"] + ": " + c["desc"] for c in cat], "passage")]
rows = {}
for f in ("dev", "test"):
    for l in open(f"{d}/{f}.jsonl"):
        r = json.loads(l)
        rows[r["id"]] = r
silver = [json.loads(l) for l in open(f"{d}/silver.jsonl")]
real_ids = [i for i, r in rows.items() if not r["prompt"].startswith("Another Claude session sent")]
qd = dict(zip(real_ids, (unit(v) for v in embed([rows[i]["prompt"] for i in real_ids], "query"))))
with open(f"{d}/embed_ranks.jsonl", "w") as fh:  # top-5 (name, cosine) per real prompt, for margin/gate analysis
    for i in real_ids:
        sc = sorted(((sum(a * b for a, b in zip(qd[i], c)), nm) for c, nm in zip(cv, names)), reverse=True)[:5]
        fh.write(json.dumps({"id": i, "top": [[nm, round(s, 4)] for s, nm in sc]}) + "\n")
major = Counter(s["silver"] for s in silver).most_common(1)[0][0]
res = {}
for split in ("dev", "test", "all"):
    t1 = t3 = n = m = 0
    margins = []
    for s in silver:
        if split != "all" and s["split"] != split:
            continue
        q = qd[s["id"]]
        sc = sorted(((sum(a * b for a, b in zip(q, c)), nm) for c, nm in zip(cv, names)), reverse=True)
        n += 1
        t1 += sc[0][1] == s["silver"]
        t3 += s["silver"] in [x[1] for x in sc[:3]]
        m += s["silver"] == major
    res[split] = {"n": n, "top1": round(t1 / n, 3), "top3": round(t3 / n, 3), "majority_floor": round(m / n, 3)}
print(json.dumps(res))
