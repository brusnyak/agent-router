#!/usr/bin/env python3
"""Worker benchmark through the router itself.

  layer 1  single worker x single-module task (gate = pytest, run again here after the router finishes: nothing is trusted)
  layer 2  orchestration: `delegate` splits the `inv` goal into subagents run by the chosen worker, integration gate = pytest

Every run gets a fresh temp git repo holding only the test file. The router repo is checked before/after: a worker that
writes outside its directory is flagged (`touched_repo`). Results append to eval/results/bench-<date>.jsonl; the summary
table is printed. No tokens/cost columns unless the worker reports them (unreported = blank, never guessed).

  python3 eval/bench_workers.py --workers nim1,omp --layer 1 --reps 1
  python3 eval/bench_workers.py --workers nim1,omp --layer 2 --tasks inv
  python3 eval/bench_workers.py --dry --workers nim1,omp,cline
Experts on your own subscription (claude, codex) are skipped unless --experts is given."""
import argparse
import collections
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TASKS = os.path.join(ROOT, "eval", "bench", "tasks")
EXPERTS = {"claude", "codex"}
L2_TASKS = {"inv"}


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True).stdout


def prepare(task):
    d = tempfile.mkdtemp(prefix=f"bench-{task}-")
    src = os.path.join(TASKS, task)
    for f in os.listdir(src):
        if f.startswith("test_"):
            shutil.copy(os.path.join(src, f), d)
    git(d, "init", "-q")
    git(d, "-c", "user.email=b@b", "-c", "user.name=bench", "add", "-A")
    git(d, "-c", "user.email=b@b", "-c", "user.name=bench", "commit", "-qm", "init")
    return d


def verify(task, d):
    gate = open(os.path.join(TASKS, task, "GATE")).read().split()
    r = subprocess.run([sys.executable] + gate[1:], cwd=d, capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def run_one(bb, layer, worker, task, rep):
    d = prepare(task)
    prompt = open(os.path.join(TASKS, task, "TASK.md")).read()
    gate = open(os.path.join(TASKS, task, "GATE")).read().strip()
    before = git(ROOT, "status", "--porcelain")
    t0 = time.time()
    row = {"ts": int(t0), "layer": layer, "worker": worker, "task": task, "rep": rep, "dir": d}
    try:
        if layer == 1:
            res = bb.run(prompt, worker=worker, gate=gate, cwd=d, isolate=False)
            row.update(state=res.get("state"), router_gate=res.get("gate_passed"), error=str(res.get("error") or res.get("output") or "")[:200]
                       if res.get("state") != "done" else "")
        else:
            res = bb.delegate(prompt, worker=worker, gate=gate, cwd=d, max_subagents=3, isolate=True)
            subs = res.get("subagents") or res.get("results") or res.get("plan") or []
            row.update(state="done" if res.get("ok", True) else "failed", router_gate=res.get("gate_passed"),
                       n_subtasks=len(subs) if hasattr(subs, "__len__") else None, error=str(res.get("error") or "")[:200])
    except Exception as e:                      # a crashing worker is a result, not a benchmark failure
        row.update(state="crash", router_gate=None, error=f"{type(e).__name__}: {e}"[:200])
    row["wall_s"] = round(time.time() - t0, 1)
    try:
        row["verified_pass"] = verify(task, d)
    except Exception as e:
        row["verified_pass"] = False
        row["error"] = (row.get("error") or "") + f" verify:{e}"[:80]
    row["touched_repo"] = git(ROOT, "status", "--porcelain") != before
    return row


def summarize(rows):
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["layer"], r["worker"])].append(r)
    lines = [f"{'layer':5} {'worker':10} {'pass':>7} {'median s':>9} {'crash/blocked':>14} {'wrote outside':>14}"]
    for (layer, w), rs in sorted(by.items()):
        ok = sum(1 for r in rs if r.get("verified_pass"))
        med = statistics.median(r["wall_s"] for r in rs)
        bad = sum(1 for r in rs if r.get("state") in ("crash", "blocked", "failed"))
        out = sum(1 for r in rs if r.get("touched_repo"))
        lines.append(f"{layer:<5} {w:10} {ok:>3}/{len(rs):<3} {med:>9} {bad:>14} {out:>14}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="nim1,omp")
    ap.add_argument("--layer", type=int, choices=(1, 2), default=1)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--experts", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "results"))
    a = ap.parse_args()
    workers = [w for w in a.workers.split(",") if w and (a.experts or w not in EXPERTS)]
    names = sorted(os.listdir(TASKS))
    tasks = a.tasks.split(",") if a.tasks else [t for t in names if (t in L2_TASKS) == (a.layer == 2)]
    plan = [(w, t, r) for w in workers for t in tasks for r in range(a.reps)]
    print(f"layer {a.layer}: {len(plan)} runs ({len(workers)} workers x {len(tasks)} tasks x {a.reps} reps); skipped experts: "
          f"{[w for w in a.workers.split(',') if w in EXPERTS and not a.experts]}")
    if a.dry:
        for p in plan:
            print("  ", *p)
        return 0
    from backbone.core import Backbone
    bb = Backbone()
    os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, "bench-" + time.strftime("%Y-%m-%d") + ".jsonl")
    rows = []
    for w, t, r in plan:
        row = run_one(bb, a.layer, w, t, r)
        rows.append(row)
        open(out, "a").write(json.dumps(row) + "\n")
        print(f"  {w:8} {t:15} rep{r} state={row['state']:8} verified={row['verified_pass']} {row['wall_s']}s {row.get('error','')[:60]}", flush=True)
    print("\n" + summarize(rows))
    print("rows appended to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
