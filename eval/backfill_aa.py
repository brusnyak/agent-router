"""Offline A/A replay of the shadow pipeline over history. No hint was ever shown, so
treat and holdout 'followed' rates must match; a big gap = measurement bug."""
import argparse, glob, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backbone import hook, hook_log
from mine_transcripts import walk

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY = "Another Claude session sent"
PROJECTS = os.path.expanduser("~/.claude/projects/*/*.jsonl")


def index_transcripts(pattern=PROJECTS):
    """prompt text -> (session_id, [skill/agent names]); first hit wins."""
    idx = {}
    for f in sorted(glob.glob(pattern)):
        stem = os.path.splitext(os.path.basename(f))[0]
        for r in walk(f):
            idx.setdefault(r["prompt"], (stem, r["skills"] + r["agents"]))
    return idx


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def replay(data_dir, ranks_path, out_dir, pattern=PROJECTS, holdout_pct=50):
    ranks = {r["id"]: r for r in _jsonl(ranks_path)}
    idx = index_transcripts(pattern)
    os.makedirs(out_dir, exist_ok=True)
    rpath, opath = os.path.join(out_dir, "receipts.jsonl"), os.path.join(out_dir, "outcomes.jsonl")
    open(opath, "w").close()
    receipts = []
    for split in ("dev", "test"):
        p = os.path.join(data_dir, split + ".jsonl")
        if not os.path.exists(p):
            continue
        for row in _jsonl(p):
            if row["id"] not in ranks or row["prompt"].startswith(RELAY) or row["prompt"] not in idx:
                continue
            sid, names = idx[row["prompt"]]
            rc = hook.decide({"prompt": row["prompt"], "session_id": sid, "prompt_id": row["id"]},
                             holdout_pct=holdout_pct)
            rc["would_surface"] = [t[0] for t in ranks[row["id"]]["top"][:3]]
            receipts.append(rc)
            for i, n in enumerate(names):
                hook_log.append_outcome(opath, n, sid, row["id"], "%s-%d" % (row["id"], i), ts=rc["ts"])
    with open(rpath, "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in receipts)
    return receipts, _jsonl(opath)


def verdict(rep):
    if rep["insufficient"]:
        return "A/A INSUFFICIENT (need >= %d prompts per arm)" % hook_log.MIN_N
    ok = abs(rep["treat_minus_holdout_pp"]) <= 5 or rep["p_value"] > 0.05
    return "A/A OK" if ok else "A/A SUSPECT"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.path.join(HERE, "heldout_v2"))
    ap.add_argument("--ranks", default=None)
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    out = a.out_dir or tempfile.mkdtemp(prefix="backfill_aa_")
    rec, outc = replay(a.data_dir, a.ranks or os.path.join(a.data_dir, "embed_ranks.jsonl"), out)
    rep = hook_log.report(rec, outc)
    print(hook_log.format_report(rep))
    print(verdict(rep))
    print("out-dir:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
