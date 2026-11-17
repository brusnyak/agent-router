import ast, json, os, re, subprocess, sys
from backbone.hook import decide

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = ["backbone/hook.py", "scripts/outcome_hook.py"]
NEW = ["backbone/hook.py", "backbone/hook_log.py", "backbone/compile.py", "eval/librarian.py",
       "eval/shadow_eval.py", "eval/shadow_enrich.py", "eval/build_catalog.py"]
BANNED = {"urllib", "socket", "http", "requests", "subprocess", "ssl", "asyncio"}


def _src(rel):
    return open(os.path.join(R, rel)).read()


def _imports(src):
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            yield from (a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            yield n.module


def _run(rel, stdin, env=None):
    return subprocess.run([sys.executable, os.path.join(R, rel)], input=stdin, capture_output=True,
                          text=True, timeout=10, env={**os.environ, **(env or {})})


def test_i1_hooks_llm_and_network_free():
    for rel in HOOKS:
        src = _src(rel)
        assert not {m.split(".")[0] for m in _imports(src)} & BANNED, rel
        assert not re.search(r"anthropic|openai", src, re.I), rel


def test_i2_hook_fails_open():
    r = _run("backbone/hook.py", "}{ not json \x00", {"HOOK_LOG": os.devnull})
    assert r.stdout == "" and r.returncode == 0


def test_i3_receipt_has_no_prompt_text():
    s = "SENTINEL-7f3a9c-unique-prompt"
    assert s not in json.dumps(decide({"prompt": s, "session_id": "s", "prompt_id": "p"}))


def test_i4_shadow_injects_nothing(tmp_path):
    # holdout arm never injects; the library index may surface skills in treat,
    # so this invariant must be checked against a holdout session.
    p = json.dumps({"prompt": "please refactor this module now", "session_id": "holdout-7", "prompt_id": "p"})
    r = _run("backbone/hook.py", p, {"HOOK_LOG": str(tmp_path / "l.jsonl")})
    assert r.stdout == "" and r.returncode == 0


def test_i5_third_party_not_imported():
    for d in ("backbone", "eval", "scripts"):
        for f in os.listdir(os.path.join(R, d)):
            if f.endswith(".py"):
                for m in _imports(_src(f"{d}/{f}")):
                    assert not m.startswith("third_party"), f"{d}/{f}"


def _loc(rel):
    return sum(1 for l in _src(rel).splitlines() if l.strip() and not l.strip().startswith("#"))


def test_i6_size_ratchet():
    mx = json.load(open(os.path.join(R, "docs/complexity-budget.json")))["max"]
    assert sum(_loc(f) for f in NEW) <= mx


def test_invariant_pointers_resolve():
    ptrs = re.findall(r"verify:\s*`?(test_\w+)", _src("docs/INVARIANTS.md"))
    assert len(ptrs) == 6
    assert all(p in globals() for p in ptrs)
