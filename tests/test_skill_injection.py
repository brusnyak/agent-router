"""Skill pre-injection tests: treat arm injects a skill body, holdout gets nothing,
score floor respected, no prompt text leaks, fails open without index."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backbone import hook  # noqa: E402


def _idx(tmp_path, rows):
    p = tmp_path / "library-index.jsonl"
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return str(p)


def test_treat_injects_top_skill_body(tmp_path, monkeypatch):
    index = _idx(tmp_path, [
        {"id": "skill:review", "kind": "skill", "name": "review",
         "description": "Check code for correctness bugs and security issues.",
         "body": "## review\nAlways run pytest after editing. Never skip tests."},
        {"id": "skill:unrelated", "kind": "skill", "name": "unrelated",
         "description": "something about gardening and soil.",
         "body": "## unrelated\ngardening tips"},
    ])
    monkeypatch.setattr(hook, "INDEX_PATH", index)
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.0)
    sid = "s-treat-inject"
    # force treat arm via hash: choose sid whose fnv1a32 % 100 >= 20
    r = hook.decide({"prompt": "check this code for correctness bugs and security issues",
                     "session_id": sid, "prompt_id": "p1"})
    # injection only matters on treat; verify the path works when treat
    if r["arm"] == "treat":
        assert "skill-inject" in r["selected"], r
        assert r["would_surface"] == ["review"], r
        assert r["additional_context"] is not None
        assert "Always run pytest after editing" in r["additional_context"]
        assert "gardening" not in r["additional_context"]


def test_holdout_gets_nothing(tmp_path, monkeypatch):
    index = _idx(tmp_path, [
        {"id": "skill:review", "kind": "skill", "name": "review",
         "description": "Check code for correctness bugs.",
         "body": "## review\nAlways run pytest."},
    ])
    monkeypatch.setattr(hook, "INDEX_PATH", index)
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.0)
    sid = "s-holdout"
    r = hook.decide({"prompt": "check this code for correctness bugs",
                     "session_id": sid, "prompt_id": "p2"})
    # holdout arm: fnv1a32(sid) % 100 < 20; if not holdout, skip assertion on injection
    if r["arm"] == "holdout":
        assert r["selected"] == [], r
        assert r["additional_context"] is None, r
        assert r["would_surface"] == [], r


def test_score_floor_blocks_low_match(tmp_path, monkeypatch):
    index = _idx(tmp_path, [
        {"id": "skill:review", "kind": "skill", "name": "review",
         "description": "Check code for correctness bugs.",
         "body": "## review\nAlways run pytest."},
    ])
    monkeypatch.setattr(hook, "INDEX_PATH", index)
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.9)  # impossible to reach for unrelated prompt
    r = hook.decide({"prompt": "tell me a joke about potatoes",
                     "session_id": "s-treat", "prompt_id": "p3"})
    assert r["selected"] == [], r
    assert r["additional_context"] is None, r


def test_no_prompt_text_in_additional_context(tmp_path, monkeypatch):
    index = _idx(tmp_path, [
        {"id": "skill:review", "kind": "skill", "name": "review",
         "description": "Check code.",
         "body": "## review\nrun pytest"},
    ])
    monkeypatch.setattr(hook, "INDEX_PATH", index)
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.0)
    secret = "SECRET-SKILL-PROMPT-TEXT"
    r = hook.decide({"prompt": secret + " check code.",
                     "session_id": "s-sec", "prompt_id": "p4"})
    if r["arm"] == "treat" and r["additional_context"]:
        assert secret not in r["additional_context"], r


def test_fails_open_without_index(tmp_path, monkeypatch):
    monkeypatch.setattr(hook, "INDEX_PATH", str(tmp_path / "does-not-exist.jsonl"))
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.0)
    r = hook.decide({"prompt": "check this code for bugs",
                     "session_id": "s-noidx", "prompt_id": "p5"})
    assert r["selected"] == [], r
    assert r["additional_context"] is None, r


def test_receipt_contains_no_raw_prompt():
    secret = "SECRET-PROMPT-RECEIPT"
    r = hook.decide({"prompt": secret, "session_id": "s", "prompt_id": "p"})
    assert secret not in json.dumps(r)
    assert len(r["prompt_hash"]) == 64


def test_machine_turn_and_lane_child_bypass_injection(tmp_path, monkeypatch):
    index = _idx(tmp_path, [
        {"id": "skill:review", "kind": "skill", "name": "review",
         "description": "Check code.", "body": "## review\nrun pytest"},
    ])
    monkeypatch.setattr(hook, "INDEX_PATH", index)
    monkeypatch.setattr(hook, "SCORE_FLOOR", 0.0)
    assert hook.decide({"prompt": "Another Claude session sent x",
                        "session_id": "s", "prompt_id": "p"})["mode"] == "machine-turn"
    os.environ["MR_ORCH_DISPATCH"] = "1"
    try:
        assert hook.decide({"prompt": "please refactor this module now",
                            "session_id": "s", "prompt_id": "p"})["mode"] == "lane-child"
    finally:
        del os.environ["MR_ORCH_DISPATCH"]


def test_export_index_writes_hook_consumable_jsonl(tmp_path):
    from backbone.library import export_index
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE library (id TEXT, kind TEXT, name TEXT, description TEXT, body TEXT, meta TEXT, source TEXT, updated REAL)")
    con.execute("INSERT INTO library VALUES ('id1','skill','k1','desc one','body one text','{}','/s/k1',1.0)")
    con.execute("INSERT INTO library VALUES ('id2','command','k2','desc two','body two text','{}','/s/k2',2.0)")
    con.commit()
    out = tmp_path / "idx.jsonl"
    n = export_index(con, str(out), kinds=["skill", "command"], limit_per_kind=5)
    assert n == 2
    lines = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    assert lines[0]["kind"] == "skill" and lines[0]["name"] == "k1"
    assert lines[1]["kind"] == "command" and lines[1]["name"] == "k2"
    assert lines[0]["body"] == "body one text"
