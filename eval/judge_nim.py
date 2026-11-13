"""Blind NIM judge: which catalog entry should serve each prompt. stdlib only.
Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/judge_nim.py IN.jsonl OUT.jsonl [CATALOG.json] [THREADS]
IN rows: {id, prompt}. Resumable: ids already in OUT are skipped."""
import json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"
KEYS = [os.environ[k] for k in ("NIM_1", "NIM_2", "NIM_3") if os.environ.get(k)]
inp, outp = sys.argv[1], sys.argv[2]
cat = json.load(open(sys.argv[3] if len(sys.argv) > 3 else "eval/heldout/pilot/catalog.json"))
threads = int(sys.argv[4]) if len(sys.argv) > 4 else 6
names = {c["name"]: c["kind"] for c in cat}
SYS = ("You label prompts. Pick the single catalog entry that SHOULD serve the prompt best, or none for chit-chat, "
       "continuations or no clear fit. Answer with ONLY this JSON, no other text: "
       '{"label":"<name or none>","conf":0.0-1.0,"alt":"<name or none>","why":"<=10 words"}\n\nCATALOG:\n'
       + "\n".join(f"- {c['name']}: {c['desc'][:160]}" for c in cat))


def judge(args):
    i, r = args
    res = {"id": r["id"], "label": "none", "kind": "none", "conf": 0.0, "alt": "none", "why": "error"}
    for attempt in range(3):
        try:
            body = json.dumps({"model": MODEL, "temperature": 0, "max_tokens": 600,
                               "chat_template_kwargs": {"enable_thinking": False},
                               "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": r["prompt"][:1500]}]}).encode()
            req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + KEYS[(i + attempt) % len(KEYS)], "Content-Type": "application/json"})
            m = json.load(urllib.request.urlopen(req, timeout=90))["choices"][0]["message"]
            txt = m.get("content") or m.get("reasoning_content") or ""
            found = re.findall(r"\{[^{}]*\"label\"[^{}]*\}", txt, re.S)
            j = json.loads(found[-1])
            lab = j.get("label", "none")
            res.update(label=lab if lab in names else "none", conf=float(j.get("conf", 0)), alt=j.get("alt", "none") if j.get("alt") in names else "none",
                       why=str(j.get("why", ""))[:80])
            res["kind"] = names.get(res["label"], "none")
            if lab not in names and lab != "none":
                res["why"] = "invalid label"
            return res
        except Exception as e:
            res["why"] = "error: " + type(e).__name__
            time.sleep(2 * (attempt + 1))
    return res


done = set()
if os.path.exists(outp):
    done = {json.loads(l)["id"] for l in open(outp) if l.strip()}
rows = [json.loads(l) for l in open(inp) if l.strip()]
todo = [(i, r) for i, r in enumerate(rows) if r["id"] not in done]
with open(outp, "a") as out, ThreadPoolExecutor(threads) as ex:
    for res in ex.map(judge, todo):
        out.write(json.dumps(res) + "\n")
        out.flush()
