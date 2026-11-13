"""Measure the existing ~/.agent-skills/router/router.py search against silver labels (offline, local embeddings).
Run with its venv: ~/.memory/venv/bin/python eval/baseline_router.py [eval/heldout_v2] [query_chars]
Only active entries whose name is in our catalog are counted, so the comparison matches baseline_embed.py."""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.expanduser("~/.agent-skills/router"))
import router  # noqa: E402  (no side effects at import beyond the venv check)

d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
qchars = int(sys.argv[2]) if len(sys.argv) > 2 else 300
norm = lambda s: str(s).strip().strip("\"'")
names = {norm(c["name"]) for c in json.load(open(f"{d}/judge/catalog.json"))}
rows = {}
for f in ("dev", "test"):
    for l in open(f"{d}/{f}.jsonl"):
        r = json.loads(l)
        rows[r["id"]] = r
silver = [json.loads(l) for l in open(f"{d}/silver.jsonl")]
major = Counter(s["silver"] for s in silver).most_common(1)[0][0]
from fastembed import TextEmbedding  # noqa: E402
import numpy as np  # noqa: E402

_model = TextEmbedding(router.MODEL)  # router.embed() reloads the model on every call; load once
router.embed = lambda texts: np.array(list(_model.embed(texts)), dtype="float32")
res = {}
dump = open(f"{d}/router_ranks.jsonl", "w")
ranked = {}  # one search per prompt, reused for every split
for s in silver:
    hits = router.search(rows[s["id"]]["prompt"][:qchars], k=60)
    ranked[s["id"]] = [h["id"].split(":")[-1] for h in hits if h["status"] == "active" and h["id"].split(":")[-1] in names]
    dump.write(json.dumps({"id": s["id"], "top": [[h["id"], round(h["sem"], 4), round(h["score"], 5)] for h in hits[:5]]}) + "\n")
    dump.flush()
for split in ("dev", "test", "all"):
    n = t1 = t3 = m = 0
    for s in silver:
        if split != "all" and s["split"] != split:
            continue
        top = ranked[s["id"]]
        n += 1
        t1 += bool(top) and top[0] == s["silver"]
        t3 += s["silver"] in top[:3]
        m += s["silver"] == major
    res[split] = {"n": n, "top1": round(t1 / n, 3), "top3": round(t3 / n, 3), "majority_floor": round(m / n, 3)}
print(json.dumps({"query_chars": qchars, **res}))
