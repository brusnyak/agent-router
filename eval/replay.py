"""T9-lite: same NIM model, same tasks, two arms. single = one attempt, no feedback. loop = router graph (gate + feedback, 2 attempts).
Run: python3 eval/replay.py [--trials 2] -> data/eval/replay-<ts>.json. Pass = the task's pytest file passes (run by this script)."""
import json, os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import TASKS
from backbone.core import Backbone
from backbone.workspace import scratch_repo

GATE = "python3 -m pytest -q -x test_task.py"


def prep(t):
    d = scratch_repo("t9-")
    open(os.path.join(d, "test_task.py"), "w").write(t["test"])
    subprocess.run(["git", "add", "-A"], cwd=d)
    subprocess.run(["git", "-c", "user.email=b@b", "-c", "user.name=b", "commit", "-qm", "t"], cwd=d)
    return d


def passes(d):
    p = subprocess.run(GATE, shell=True, cwd=d, capture_output=True, text=True, timeout=120)
    return p.returncode == 0


def main():
    trials = int(sys.argv[sys.argv.index("--trials") + 1]) if "--trials" in sys.argv else 1
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    bb = Backbone()
    rows = []
    for t in [x for x in TASKS if not only or x['id'] in only]:
        for trial in range(trials):
            for arm in ("single", "loop"):
                d = prep(t)
                t0 = time.time()
                try:
                    if arm == "single":  # in place, no gate -> exactly one attempt; the evaluator checks afterwards
                        r = bb.run(f"@nim1 {t['prompt']}", cwd=d, isolate=False, use_vault=False)
                        ok = passes(d)
                    else:  # isolated worktree + gate loop; evaluator re-runs the test on the produced patch
                        r = bb.run(f"@nim1 {t['prompt']}", cwd=d, gate=GATE, use_vault=False, escalate="")
                        ok = bool(r.get("verified"))
                    rows.append({"task": t["id"], "trial": trial, "arm": arm, "pass": ok, "attempts": r.get("attempts"),
                                 "s": round(time.time() - t0, 1), "state": r.get("state")})
                except Exception as e:
                    rows.append({"task": t["id"], "trial": trial, "arm": arm, "pass": False, "error": str(e)[:120]})
                shutil.rmtree(d, ignore_errors=True)
                print(rows[-1], flush=True)
    summ = {a: {"n": sum(r["arm"] == a for r in rows), "pass": sum(r["arm"] == a and r["pass"] for r in rows)} for a in ("single", "loop")}
    out = {"model": bb.cfg["nim"]["model"], "trials": trials, "summary": summ, "rows": rows}
    os.makedirs("data/eval", exist_ok=True)
    path = f"data/eval/replay-{time.strftime('%Y%m%d-%H%M%S')}.json"
    json.dump(out, open(path, "w"), indent=2)
    print("SUMMARY", summ, path)


if __name__ == "__main__":
    main()
