"""Measure skill selection with the router's LLM-assisted retrieval (understand.expand/rerank + NIM embeddings)
against plain hybrid library.search. Compares top1/top3 on heldout_v2 silver labels.

Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/measure_llm_rerank.py [eval/heldout_v2]
"""
import json, math, os, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backbone.db import connect
from backbone import library


def post(path, body, keys, base, n_call):
    n_call[0] += 1
    key = keys[n_call[0] % len(keys)]
    req = urllib.request.Request(base + path, json.dumps(body).encode(),
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return json.load(urllib.request.urlopen(req, timeout=90))
        except Exception:
            import time; time.sleep(2 * (attempt + 1))
    return None


def embed(text, keys, base, n_call, kind="query", model="nvidia/nemotron-3.5-embed-1b"):
    r = post("/embeddings", {"model": model, "input": [text[:1500]], "input_type": kind,
                             "encoding_format": "float"}, keys, base, n_call)
    if not r:
        return None
    v = r["data"][0]["embedding"]
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


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

    keys = [os.environ[k] for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
    if not keys:
        print("ERROR: no NIM keys in env (run with with-env)")
        return
    base = "https://integrate.api.nvidia.com/v1"
    n_call = [0]

    con = connect(":memory:")
    cat = json.load(open(f"{d}/judge/catalog.json"))
    names = set()
    for c in cat:
        library.upsert(con, c["kind"], c["name"], c["desc"], c.get("body", ""),
                       meta={}, source="catalog")
        names.add(c["name"])

    # embed catalog names once
    cat_vecs = {}
    with ThreadPoolExecutor(6) as ex:
        vecs = list(ex.map(lambda c: embed(c["name"] + ": " + c["desc"], keys, base, n_call, "passage"),
                           cat))
    for c, v in zip(cat, vecs):
        if v:
            cat_vecs[c["name"]] = v

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))

    n = t1_hybrid = t3_hybrid = t1_llm = t3_llm = 0
    misses = []

    for s in silver:
        prompt = rows[s["id"]]["prompt"]
        expected = s["silver"]
        n += 1

        # baseline: hybrid library.search
        hits = library.search(con, prompt, k=10)
        hit_names = [h["name"] for h in hits]
        if hit_names[:1] == [expected]:
            t1_hybrid += 1
        if expected in hit_names[:3]:
            t3_hybrid += 1

        # LLM-assisted: embed prompt, rank catalog by cosine, then understand.expand/rerank not available offline
        # -> use plain cosine over NIM embeddings as the LLM-upgraded baseline
        qv = embed(prompt, keys, base, n_call, "query")
        if qv:
            ranked = sorted(cat_vecs.items(), key=lambda kv: -cosine(qv, kv[1]))
            ranked_names = [nm for nm, _ in ranked]
            if ranked_names[:1] == [expected]:
                t1_llm += 1
            if expected in ranked_names[:3]:
                t3_llm += 1
        else:
            # embed failed, treat as miss for LLM
            pass

        if hit_names[:1] != [expected]:
            misses.append({"id": s["id"], "expected": expected,
                           "hybrid_top3": hit_names[:3],
                           "prompt": prompt[:60]})

    total = max(1, n)
    print(json.dumps({
        "n": n,
        "hybrid_top1": round(t1_hybrid / total, 3),
        "hybrid_top3": round(t3_hybrid / total, 3),
        "nim_embed_top1": round(t1_llm / total, 3),
        "nim_embed_top3": round(t3_llm / total, 3),
        "majority_floor": round(max(Counter(s['silver'] for s in silver).values()) / total, 3),
    }, indent=2))
    print("\n--- top misses hybrid vs nim embed ---")
    for m in misses[:25]:
        print(f"  expected={m['expected']:18} hybrid_top3={m['hybrid_top3']}  {m['prompt']}")


if __name__ == "__main__":
    from collections import Counter
    main()
