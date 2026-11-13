from backbone import compose, understand


def chat(_):
    return '{"task_class": "draft", "goal": "g"}'


def test_analyze_named():
    raw = "fix /Users/x/a.py see https://ex.com/p and `foo_bar` now"
    nt = understand.analyze(chat, raw).get("named_things")
    assert nt and any("a.py" in n for n in nt) and any("ex.com" in n for n in nt) and "foo_bar" in nt


def test_compose_line_and_cap():
    out, _ = compose.build("r", {"named_things": ["a", "b"]})
    assert "Named things (verbatim): a, b" in out
    out, _ = compose.build("r", {"named_things": ["x" * 300, "y" * 300]})
    assert max(len(ln) for ln in out.splitlines() if ln.startswith("Named")) <= 400


def test_compose_none():
    out, _ = compose.build("r", {"named_things": []})
    assert "Named things" not in out
