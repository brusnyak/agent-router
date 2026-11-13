import json, os, subprocess, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*a):
    return subprocess.run([sys.executable, "-m", "backbone", *a], cwd="/", capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=R))


def test_help():
    h = run("--help").stdout
    for n in ("librarian", "router-report", "compile", "aa-replay", "enrich"):
        assert n in h


def test_compile_no_llm():
    o = run("compile", "--no-llm", "fix /tmp/a/b.py see https://x.io/p?q=1 now").stdout
    assert "/tmp/a/b.py" in o and "https://x.io/p?q=1" in o


def test_router_report_json(tmp_path):
    r, o = tmp_path / "r.jsonl", tmp_path / "o.jsonl"
    r.write_text(""); o.write_text("")
    p = run("router-report", "--json", "--receipts", str(r), "--outcomes", str(o))
    assert p.returncode == 0 and "arms" in json.loads(p.stdout)
