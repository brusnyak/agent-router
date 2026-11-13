import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
import spotcheck_cards as sc  # noqa: E402


def w(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows))


def U(t):
    return {"type": "user", "message": {"content": t}}


def A(t, tools=()):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}] + [{"type": "tool_use", "name": n, "input": {}} for n in tools]}}


def test_cards(tmp_path):
    P1 = "please refactor the router module now"
    P2 = "Another Claude session sent: do the thing please ok"
    P3 = "use key " + "sk-" + "abcdefghij" + "klmnopqrstuv" + " in the config"  # fake fixture, split so scanners ignore it
    w(tmp_path / "proj" / "a.jsonl", [U("hello first message here ok ok ok"), A("PREV TEXT\napi_key = zzz\nsafe line"), U(P1), A("NEXT TEXT", ["Read", "Edit"]), U(P2)])
    h = tmp_path / "h"
    w(h / "dev.jsonl", [{"id": "d1", "prompt": P1, "label": "refactor", "candidates": ["refactor"]}, {"id": "d2", "prompt": P2, "label": "x"}])
    w(h / "test.jsonl", [{"id": "t1", "prompt": P3, "label": "y"}])
    w(h / "judge" / "nim.jsonl", [{"id": "d1", "label": "refactor", "why": "WHYTEXT"}])
    (h / "judge" / "catalog.json").write_text(json.dumps({"refactor": "restructure code"}))
    out = tmp_path / "o.md"
    assert sc.build(30, 0, str(tmp_path), str(h), str(out)) == 1
    s = out.read_text()
    for x in ("PREV TEXT", "safe line", "NEXT TEXT", "Read", "WHYTEXT", "restructure code", "(proj)"):
        assert x in s
    assert "api_key" not in s and "Another Claude" not in s and "sk-abc" not in s
    assert "Would a hint for `refactor`" in s and "better label:" in s
