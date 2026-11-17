"""End-to-end test of `backbone delegate` on a scratch git repo.

Creates a scratch repo with two files needing changes, delegates a multi-file
goal, verifies subagents ran, patches were produced, and the combined gate passed.
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main():
    d = tempfile.mkdtemp(prefix="delegate-e2e-")
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=d, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=d, check=True)
    # two files to touch
    for name, content in [("a.py", "x = 1\n"), ("b.py", "y = 2\n")]:
        with open(os.path.join(d, name), "w") as f:
            f.write(content)
    git(["add", "."], cwd=d)
    git(["commit", "-q", "-m", "init"], cwd=d)

    # add a gate target file that the delegate integrator should verify exists
    result = subprocess.run(
        [sys.executable, "-m", "backbone", "delegate",
         "Add a README.md and a CHANGELOG.md to the repo",
         "--cwd", d, "--project", "", "--gate", "noop",
         "--max-subagents", "2", "--read-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
        env={**os.environ},
    )
    print("STDOUT:", result.stdout[-2000:])
    print("STDERR:", result.stderr[-1000:])
    print("RC:", result.returncode)

    try:
        out = json.loads(result.stdout)
    except Exception:
        print("FAIL: output not JSON")
        return 1

    ok = out.get("ok")
    n = out.get("subagents")
    results = out.get("results", [])
    states = [r["state"] for r in results]
    print(f"ok={ok} subagents={n} states={states}")
    for r in results:
        print(f"  {r['subagent']} {r['state']} gate={r['gate_passed']} verified={r['verified']} err={r['error'][:60]}")

    success = ok and n >= 1 and all(s == "done" for s in states)
    print("PASS" if success else "FAIL")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
