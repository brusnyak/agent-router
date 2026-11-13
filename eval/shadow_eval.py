"""Offline replay of the margin-gate hook decision over the silver set. No network, no LLM."""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

D = Path(__file__).parent / "heldout_v2"


def read(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def norm(n):
    """'kind:name:hash' -> 'name', 'kind:name' -> 'name', plain name untouched."""
    p = str(n).split(":")
    return p[1] if len(p) == 3 else p[-1]


def margin(top):
    s = [c[1] for c in top]
    return s[0] - s[1] if len(s) > 1 else (s[0] if s else 0.0)


def load(source, split, d=D):
    silver = {r["id"]: r for r in read(Path(d) / "silver.jsonl")}
    rows = []
    for r in read(Path(d) / (source + "_ranks.jsonl")):
        s = silver.get(r["id"])
        if s and r["top"] and (split == "all" or s["split"] == split):
            rows.append(([norm(c[0]) for c in r["top"]], margin(r["top"]), s["silver"]))
    return rows


def evaluate(rows, T):
    kept = [r for r in rows if r[1] >= T]
    n, k = len(rows), len(kept)
    if not k:
        return dict(T=T, n=n, coverage=0.0, top1=0.0, top3=0.0, floor=0.0)
    return dict(T=T, n=n, coverage=k / n,
                top1=sum(r[0][0] == r[2] for r in kept) / k,
                top3=sum(r[2] in r[0][:3] for r in kept) / k,
                floor=Counter(r[2] for r in kept).most_common(1)[0][1] / k)


def main(argv=None, d=D):
    a = argparse.ArgumentParser()
    a.add_argument("--source", choices=["router", "embed"], required=True)
    a.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    a.add_argument("--thresholds", default="0,0.01,0.02,0.05,0.1")
    a.add_argument("--tune", action="store_true")
    a.add_argument("--final", action="store_true")
    o = a.parse_args(argv)
    if o.split != "dev" and not o.final:
        print("refused: test split needs --final", file=sys.stderr)
        return 2
    ts = [float(t) for t in o.thresholds.split(",")]
    if o.tune:  # dev only, always
        dev = load(o.source, "dev", d)
        ok = [e for e in (evaluate(dev, t) for t in ts) if e["coverage"] >= 0.25]
        if not ok:
            print("no threshold meets coverage >= 0.25", file=sys.stderr)
            return 1
        best = max(ok, key=lambda e: (e["top3"], -e["T"]))
        (Path(d) / "gate.json").write_text(json.dumps({"source": o.source, "T": best["T"], "dev": best}))
        print("tuned T=%s on dev" % best["T"])
        return 0
    rows = load(o.source, o.split, d)
    print("T\tn\tcov\ttop1\ttop3\tfloor")
    for t in ts:
        e = evaluate(rows, t)
        print("%s\t%d\t%.3f\t%.3f\t%.3f\t%.3f" % (t, e["n"], e["coverage"], e["top1"], e["top3"], e["floor"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
