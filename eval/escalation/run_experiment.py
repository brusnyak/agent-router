#!/usr/bin/env python3
"""Escalation-accuracy experiment.

Runs each labelled task through `bb.ask(..., dry=True)` with experts temporarily
available in the allowed-workers set (dry mode never calls an expert, so zero
spend). Records the worker the router would pick, then computes escalation
precision/recall vs the gold label, plus always-cheap and always-expert baselines.

Tasks run in small sequential batches with incremental checkpointing so partial
results survive a shell timeout. Each batch reuses one Backbone instance.

Usage:
  with-env NIM_1 -- python3 eval/escalation/run_experiment.py [batch_start]
"""
import json, os, sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backbone.core import Backbone

LABELLED = os.path.join(ROOT, "eval", "escalation", "labelled.jsonl")
EXPERTS = {"claude", "codex"}
BATCH = 8


def _allow_experts(bb):
    bb.cfg.setdefault("decide", {})["allow_experts"] = True


def run_batch(bb, tasks):
    rows = []
    _allow_experts(bb)
    for t in tasks:
        try:
            res = bb.ask(t["prompt"], dry=True)
        except Exception as e:
            res = {"plan": {"worker": "", "task_class": "", "decided_by": f"error:{type(e).__name__}"}}
        plan = res.get("plan", {}) if res else {}
        worker = plan.get("worker") or ""
        rows.append({
            "id": t["id"], "gold": t["gold"], "task_class": t.get("task_class", ""),
            "predicted": "escalate" if worker in EXPERTS else "cheap",
            "worker": worker, "router_task_class": plan.get("task_class") or "",
            "decided_by": plan.get("decided_by"), "tier_reason": plan.get("tier_reason"),
            "prompt": t["prompt"][:80],
        })
    return rows


def summarize(rows, path):
    n = len(rows)
    if not n:
        print("no rows yet"); return
    n_escalate_gold = sum(1 for r in rows if r["gold"] == "escalate")
    tp = sum(1 for r in rows if r["gold"] == "escalate" and r["predicted"] == "escalate")
    fp = sum(1 for r in rows if r["gold"] == "cheap" and r["predicted"] == "escalate")
    fn = sum(1 for r in rows if r["gold"] == "escalate" and r["predicted"] == "cheap")
    tn = sum(1 for r in rows if r["gold"] == "cheap" and r["predicted"] == "cheap")
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / n
    always_cheap_acc = tn / n
    always_expert_precision = n_escalate_gold / n
    always_expert_acc = n_escalate_gold / n
    print(f"n={n}  gold_escalate={n_escalate_gold}  gold_cheap={n - n_escalate_gold}")
    print(f"Router:       precision={precision:.3f} recall={recall:.3f} f1={f1:.3f} accuracy={accuracy:.3f}  (tp={tp} fp={fp} fn={fn} tn={tn})")
    print(f"Always-cheap: precision=0.000 recall=0.000 accuracy={always_cheap_acc:.3f}")
    print(f"Always-expert: precision={always_expert_precision:.3f} recall=1.000 accuracy={always_expert_acc:.3f}")
    print("Worker distribution:", dict(Counter(r["worker"] for r in rows)))
    print("Misses:")
    for r in rows:
        if r["gold"] != r["predicted"]:
            print(f"  {r['id']}: gold={r['gold']:8} pred={r['predicted']:8} worker={r['worker']:10} {r['prompt']}")
    out = {"n": n, "gold_escalate": n_escalate_gold,
           "router": {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
                      "accuracy": round(accuracy, 4), "tp": tp, "fp": fp, "fn": fn, "tn": tn},
           "baselines": {"always_cheap": {"precision": 0.0, "recall": 0.0, "accuracy": round(always_cheap_acc, 4)},
                         "always_expert": {"precision": round(always_expert_precision, 4), "recall": 1.0,
                                           "accuracy": round(always_expert_acc, 4)}},
           "rows": rows}
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {path}")


def main():
    tasks = [json.loads(l) for l in open(LABELLED) if l.strip()]
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    path = os.path.join(ROOT, "eval", "escalation", "results.json")
    rows = []
    if os.path.exists(path):
        try:
            rows = json.load(open(path)).get("rows", [])
        except Exception:
            rows = []
    done_ids = {r["id"] for r in rows}
    pending = [t for t in tasks if t["id"] not in done_ids]
    pending = pending[start:start + BATCH]
    if not pending:
        print("nothing pending; summarizing existing results")
        summarize(rows, path)
        return
    print(f"running batch: {[t['id'] for t in pending]}")
    bb = Backbone()
    new_rows = run_batch(bb, pending)
    rows.extend(new_rows)
    rows.sort(key=lambda r: r["id"])
    summarize(rows, path)


if __name__ == "__main__":
    main()
