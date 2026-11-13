"""Does a dictation->card rewrite improve retrieval? raw[:300] vs compiled query, same NIM embedder, same silver labels.
Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/compile_test.py [eval/heldout_v2] [THREADS]
Caveat: silver labels were made by LLMs reading the raw prompt, so a gain here is partly circular. Prompts go to NIM (owner-approved)."""
import json, math, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
threads = int(sys.argv[2]) if len(sys.argv) > 2 else 6
KEYS = [os.environ[k] for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
BASE = "https://integrate.api.nvidia.com/v1"
CHAT, EMB = "nvidia/nemotron-3.5-super-vl-120b-a12b", "nvidia/nemotron-3.5-embed-1b"
norm = lambda s: str(s).strip().strip("\"'")
COMPILER = ("Rewrite the owner's raw dictated message as a compact card. Strip filler, hesitation and emotion. Keep every filename, tool name, number "
            "and proper noun EXACTLY as written; invent nothing. Answer with ONLY this JSON: "
            '{"goal":"<=25 words","task_class":"<=4 words, e.g. research, code-fix, review, outreach, planning, ops","constraints":"<=20 words or empty",'
            '"named_things":["verbatim names/files/tools"]}')
n_call = [0]


def post(path, body):
    for attempt in range(4):
        n_call[0] += 1
        req = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                                     {"Authorization": "Bearer " + KEYS[n_call[0] % len(KEYS)], "Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=90))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def embed(text, kind):
    r = post("/embeddings", {"model": EMB, "input": [text[:1500]], "input_type": kind, "encoding_format": "float"})
    if not r:
        return None
    v = r["data"][0]["embedding"]
    n = math.sqrt(sum(x * x for x in v)) or 1
    return [x / n for x in v]


def compile_card(prompt):
    r = post("/chat/completions", {"model": CHAT, "temperature": 0, "max_tokens": 500, "chat_template_kwargs": {"enable_thinking": False},
                                   "messages": [{"role": "system", "content": COMPILER}, {"role": "user", "content": prompt[:1500]}]})
    try:
        txt = r["choices"][0]["message"].get("content") or ""
        j = json.loads(re.findall(r"\{.*\}", txt, re.S)[-1])
        return " ".join([str(j.get("goal", "")), str(j.get("task_class", "")), str(j.get("constraints", "")), " ".join(map(str, j.get("named_things", [])))]).strip()
    except Exception:
        return None


cat = json.load(open(f"{d}/judge/catalog.json"))
names = [norm(c["name"]) for c in cat]
with ThreadPoolExecutor(threads) as ex:
    cv = list(ex.map(lambda c: embed(c["name"] + ": " + c["desc"], "passage"), cat))
    rows = {}
    for f in ("dev", "test"):
        for l in open(f"{d}/{f}.jsonl"):
            r = json.loads(l)
            rows[r["id"]] = r
    silver = [json.loads(l) for l in open(f"{d}/silver.jsonl")]
    raw_q = list(ex.map(lambda s: embed(rows[s["id"]]["prompt"][:300], "query"), silver))
    cards = list(ex.map(lambda s: compile_card(rows[s["id"]]["prompt"]), silver))
    comp_q = list(ex.map(lambda c: embed(c, "query") if c else None, cards))
with open(f"{d}/compiled_cards.jsonl", "w") as fh:
    for s, c in zip(silver, cards):
        fh.write(json.dumps({"id": s["id"], "card": c}) + "\n")


def rank(q):
    return [nm for _, nm in sorted(((sum(a * b for a, b in zip(q, c)), nm) for c, nm in zip(cv, names)), reverse=True)]


out = {}
for split in ("dev", "test", "all"):
    r = {"raw300": [0, 0], "compiled": [0, 0], "n": 0, "compile_failed": 0}
    for s, rq, cq in zip(silver, raw_q, comp_q):
        if (split != "all" and s["split"] != split) or rq is None:
            continue
        r["n"] += 1
        a = rank(rq)
        r["raw300"][0] += a[0] == s["silver"]
        r["raw300"][1] += s["silver"] in a[:3]
        if cq is None:
            r["compile_failed"] += 1
            continue
        b = rank(cq)
        r["compiled"][0] += b[0] == s["silver"]
        r["compiled"][1] += s["silver"] in b[:3]
    n = max(1, r["n"])
    out[split] = {"n": r["n"], "compile_failed": r["compile_failed"], "raw300_top1_top3": [round(x / n, 3) for x in r["raw300"]],
                  "compiled_top1_top3": [round(x / n, 3) for x in r["compiled"]]}
print(json.dumps(out))
