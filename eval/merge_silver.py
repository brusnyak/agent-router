"""Merge judge outputs into silver labels. stdlib only. Data stays local (eval/heldout_v2 is gitignored).
Usage: python3 eval/merge_silver.py [eval/heldout_v2]
Writes judge/haiku_todo.jsonl (disagreements to send to the third judge) and, once judge/haiku*.jsonl exist, silver.jsonl.
Rule: relayed machine prompts excluded; silver = at least 2 of the judges agree on the same non-none label."""
import glob, json, os, sys
from collections import Counter

d = sys.argv[1] if len(sys.argv) > 1 else "eval/heldout_v2"
J = f"{d}/judge"
norm = lambda s: str(s).strip().strip("\"'")
names = {norm(c["name"]) for c in json.load(open(f"{J}/catalog.json"))}
rows = {}
for f in ("dev", "test"):
    for l in open(f"{d}/{f}.jsonl"):
        r = json.loads(l)
        rows[r["id"]] = {**r, "split": f}


def load(pattern):
    out = {}
    for p in sorted(glob.glob(f"{J}/{pattern}")):
        for l in open(p):
            if l.strip():
                r = json.loads(l)
                lab = norm(r.get("label", "none"))
                out[r["id"]] = {"label": lab if lab in names else "none", "conf": float(r.get("conf", 0))}
    return out


S, N, H = load("sonnet_*.jsonl"), load("nim.jsonl"), load("haiku_*.jsonl")
relay = {i for i, r in rows.items() if r["prompt"].startswith("Another Claude session sent")}
real = [i for i in rows if i not in relay]
todo = [i for i in real if i in S and i in N and S[i]["label"] != N[i]["label"]]  # differ => at least one is non-none
with open(f"{J}/todo_haiku.jsonl", "w") as fh:
    for i in todo:
        fh.write(json.dumps({"id": i, "prompt": rows[i]["prompt"][:1500]}) + "\n")

silver, tier = {}, Counter()
for i in real:
    votes = [v[i]["label"] for v in (S, N, H) if i in v]
    c = Counter(x for x in votes if x != "none")
    if c and c.most_common(1)[0][1] >= 2:
        silver[i] = c.most_common(1)[0][0]
        tier["agree2" if len(votes) == 2 else "agree2of3" if c.most_common(1)[0][1] == 2 else "agree3"] += 1
with open(f"{d}/silver.jsonl", "w") as fh:
    for i, lab in silver.items():
        fh.write(json.dumps({"id": i, "split": rows[i]["split"], "silver": lab}) + "\n")

realdict = {i: set(rows[i]["skills"] + rows[i]["agents"]) for i in real if rows[i]["skills"] or rows[i]["agents"]}
match = sum(1 for i in realdict if silver.get(i) in realdict[i])
print(json.dumps({
    "mined": len(rows), "relay_excluded": len(relay), "real_prompts": len(real),
    "judged_sonnet": len(S), "judged_nim": len(N), "judged_haiku": len(H),
    "real_labels_old_miner": 87, "real_labels_now": len(realdict),
    "silver_labels": len(silver), "silver_tiers": dict(tier), "silver_rate": round(len(silver) / max(1, len(real)), 3),
    "silver_in_test": sum(1 for i in silver if rows[i]["split"] == "test"),
    "silver_matches_real_invoked": f"{match}/{len(realdict)}",
    "haiku_todo": len(todo), "top_silver_labels": Counter(silver.values()).most_common(8)}))
