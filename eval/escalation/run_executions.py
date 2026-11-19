#!/usr/bin/env python3
"""Gated execution experiment: real work through the router on bench tasks.

For each bench task, run three worker conditions:
  - router:   worker the router's ask() would pick (dry-mode plan)
  - cheap:    nim1 (always-cheap baseline)
  - expert:   claude (always-expert baseline)

Each run copies the task's test files into an isolated temp dir, runs the worker
with the task's GATE as the acceptance gate, then verifies with pytest.
Records state, gate_passed, verified_pass, wall_s, cost_usd (expert only).

Results append to eval/escalation/executions.json so partial runs are not lost.

Usage:
  with-env NIM_1 -- python3 eval/escalation/run_executions.py [tasks_csv]
"""
import json, os, sys, shutil, subprocess, tempfile, time, statistics, glob

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backbone.core import Backbone

TASKS = os.path.join(ROOT, "eval", "bench", "tasks")


def prepare(task):
    d = tempfile.mkdtemp(prefix=f"exec-{task}-")
    src = os.path.join(TASKS, task)
    for f in os.listdir(src):
        if f.startswith("test_"):
            shutil.copy(os.path.join(src, f), d)
    return d


def verify(task, d):
    gate = open(os.path.join(TASKS, task, "GATE")).read().split()
    r = subprocess.run([sys.executable] + gate[1:], cwd=d, capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def run_one(bb, worker, task, d):
    prompt = open(os.path.join(TASKS, task, "TASK.md")).read()
    gate = open(os.path.join(TASKS, task, "GATE")).read().strip()
    t0 = time.time()
    try:
        res = bb.run(prompt, worker=worker, gate=gate, cwd=d, isolate=False)
        state = res.get("state")
        gate_passed = res.get("gate_passed")
        error = res.get("error") or res.get("output") or ""
        meta = res.get("meta") or {}
        wall = round(time.time() - t0, 1)
    except Exception as e:
        state, gate_passed, error, meta, wall = "crash", None, f"{type(e).__name__}: {e}", {}, round(time.time() - t0, 1)
    try:
        verified = verify(task, d)
    except Exception as e:
        verified = False
    return {
        "worker": worker, "task": task, "state": state, "gate_passed": gate_passed,
        "verified_pass": verified, "wall_s": wall, "cost_usd": meta.get("cost_usd"),
        "turns": meta.get("turns"), "error": str(error)[:160],
    }


def router_pick(bb, task):
    prompt = open(os.path.join(TASKS, task, "TASK.md")).read()
    try:
        res = bb.ask(prompt, dry=True)
        plan = res.get("plan", {}) or {}
        return plan.get("worker") or ""
    except Exception:
        return ""


def main():
    tasks_csv = sys.argv[1] if len(sys.argv) > 1 else "slugify,parse_duration,chunk,csvsum,ttlcache,inv"
    tasks = [t.strip() for t in tasks_csv.split(",") if t.strip()]
    bb = Backbone()
    bb.cfg.setdefault("decide", {})["allow_experts"] = True

    path = os.path.join(ROOT, "eval", "escalation", "executions.json")
    rows = []
    if os.path.exists(path):
        try:
            rows = json.load(open(path))
        except Exception:
            rows = []
    done = {(r["task"], r["condition"]) for r in rows}

    for task in tasks:
        d = prepare(task)
        router_w = router_pick(bb, task)
        conditions = [("router", router_w or "nim1"), ("cheap", "nim1"), ("expert", "claude")]
        for label, worker in conditions:
            if (task, label) in done:
                continue
            r = run_one(bb, worker, task, d)
            r["condition"] = label
            r["router_pick"] = router_w
            rows.append(r)
            with open(path, "w") as f:
                json.dump(rows, f, indent=2)
            print(f"{task:14} {label:7} worker={worker:8} state={r['state']:8} verified={r['verified_pass']} wall={r['wall_s']}s cost={r['cost_usd']}")
    # cleanup temp dirs
    for d in glob.glob(tempfile.gettempdir() + "/exec-*"):
        try:
            shutil.rmtree(d)
        except OSError:
            pass

    print("\n=== Summary ===")
    for label in ("router", "cheap", "expert"):
        rs = [r for r in rows if r["condition"] == label]
        ok = sum(1 for r in rs if r.get("verified_pass"))
        n = len(rs)
        med = statistics.median(r["wall_s"] for r in rs) if rs else 0
        cost = sum(r["cost_usd"] or 0 for r in rs if r["worker"] == "claude")
        print(f"{label:7} pass={ok}/{n} median_wall={med}s expert_cost=${cost:.4f}")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
