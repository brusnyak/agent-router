"""Measure skill/command selection accuracy on real silver-labeled tasks.

Runs each heldout_v2 prompt through the router's plan() (classify + decide),
then checks whether the predicted worker/command matches the silver label.

Usage: with-env NIM_1 NIM_2 NIM_3 -- python3 eval/measure_routing.py [eval/heldout_v2]
"""
import json, os, sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backbone import plan as P
from backbone.bandit import Bandit


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

    # Use a fresh bandit so results are deterministic (rule order / classify only)
    bandit = Bandit(":memory:")

    n = t1_worker = t3_worker = t1_cmd = t3_cmd = n_classified = 0
    label_worker = Counter()
    predictions = []

    for s in silver:
        prompt = rows[s["id"]]["prompt"]
        expected = s["silver"]
        p = P.plan(prompt, bandit=bandit, avail=P.available())
        worker = p.get("worker") or ""
        task_class = p.get("task_class") or ""
        # command from decide-style gate hint or packet
        cmd = p.get("gate_hint") or ""

        n += 1
        label_worker[expected] += 1

        # top-1 worker match
        if worker == expected:
            t1_worker += 1
        # top-3: treat worker + fallbacks as shortlist
        shortlist = [worker] + [w for w in (p.get("fallbacks") or []) if w]
        if expected in shortlist[:3]:
            t3_worker += 1
        predictions.append({"id": s["id"], "prompt": prompt[:80], "expected": expected,
                            "predicted_worker": worker, "task_class": task_class,
                            "gate_hint": cmd, "hit": worker == expected})

    total = max(1, n)
    out = {
        "n": n,
        "worker_top1": round(t1_worker / total, 3),
        "worker_top3": round(t3_worker / total, 3),
        "majority_floor": round(max(label_worker.values()) / total, 3),
        "label_dist": dict(label_worker.most_common(10)),
    }
    print(json.dumps(out, indent=2))
    print("\n--- misses (expected vs predicted) ---")
    misses = [p for p in predictions if not p["hit"]]
    for m in misses[:30]:
        print(f"  expected={m['expected']:18} predicted={m['predicted_worker']:18} cls={m['task_class']:12} gate={m['gate_hint'][:40]}  {m['prompt']}")
    if len(misses) > 30:
        print(f"  ... and {len(misses)-30} more misses")


if __name__ == "__main__":
    main()
