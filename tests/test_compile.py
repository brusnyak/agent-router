import json
import subprocess
import sys

from backbone.compile import compile_card, entities_preserved, extract_named, render

RAW = "Fix `parse_args` in ~/proj/app.py and see https://x.io/a, use NIM_1 with MyClass. Then ship."


def test_extract():
    n = extract_named(RAW, known_names=("ship",))
    for e in ("parse_args", "~/proj/app.py", "https://x.io/a", "NIM_1", "MyClass", "ship"):
        assert e in n
    assert len(n) == len(set(n))


def test_clean_json():
    out = json.dumps({"goal": "Fix it", "task_class": "bugfix", "constraints": "none", "named_things": ["app.py"],
                      "open_questions": [{"q": "which branch?", "default": "main"}] * 5})
    c = compile_card(RAW, call=lambda s, u: "noise " + out)
    assert c["task_class"] == "bugfix" and len(c["open_questions"]) == 3
    assert not entities_preserved(RAW, c)


def test_garbage_falls_back():
    def boom(s, u):
        raise RuntimeError("x")

    for call in (lambda s, u: "no json {oops", lambda s, u: "[1]", boom):
        c = compile_card(RAW, call=call)
        assert c["task_class"] == "unknown" and c["goal"].startswith("Fix") and c["open_questions"] == []
        assert not entities_preserved(RAW, c)


def test_flags_dropped():
    c = compile_card(RAW)
    c["goal"] = "x"
    c["named_things"] = [x for x in c["named_things"] if x != "https://x.io/a"]
    assert entities_preserved(RAW, c) == ["https://x.io/a"]


def test_render():
    c = compile_card("word " * 1000)
    r = render(c, 100)
    assert len(r) <= 100 and not r.endswith("wor")
    assert "roast" not in render(compile_card(RAW)).lower()


def test_cli_no_llm():
    p = subprocess.run([sys.executable, "-m", "backbone.compile", RAW, "--no-llm"], capture_output=True, text=True)
    assert p.returncode == 0 and "Goal: Fix" in p.stdout and "~/proj/app.py" in p.stdout
