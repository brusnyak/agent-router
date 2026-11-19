import os

from backbone import enforce

HEAVY = "refactor and implement the whole module, then write tests for every file across the repo " * 3
# a session id that lands in the treat arm (fnv1a32 % 100 >= 20)
SID = next(f"s{i}" for i in range(100) if enforce.fnv1a32(f"s{i}") % 100 >= 20)
HOLD = next(f"s{i}" for i in range(100) if enforce.fnv1a32(f"s{i}") % 100 < 20)


def P(prompt=HEAVY, sid=SID, **ti):
    return {"tool_name": "Agent", "session_id": sid, "tool_input": {"prompt": prompt, **ti}}


def test_heavy_first_call_blocked_with_command():
    d = enforce.decide(P(), {})
    assert d["action"] == "block" and "python3 -m backbone run --worker" in d["reason"]


def test_repeat_goes_through():
    st = {}
    assert enforce.decide(P(), st)["action"] == "block"
    assert enforce.decide(P(), st)["action"] == "allow"


def test_escape_light_cheap_holdout_childs_pass(monkeypatch):
    assert enforce.decide(P(HEAVY + " ROUTER-OK"), {})["action"] == "allow"
    assert enforce.decide(P("fix typo in README"), {})["action"] == "allow"
    assert enforce.decide(P(model="haiku"), {})["action"] == "allow"
    assert enforce.decide(P(sid=HOLD), {})["action"] == "allow"
    monkeypatch.setenv("MR_ORCH_DISPATCH", "1")
    assert enforce.decide(P(), {})["action"] == "allow"


def test_picker_shapes_command():
    d = enforce.decide(P(), {}, picker=lambda p: {"worker": "codex", "gate_hint": "pytest -q"})
    assert "--worker codex --gate 'pytest -q'" in d["reason"]


def test_route_tag_is_honored_but_plain_heavy_still_redirected():
    for tag in ("judgment", "browser", "mcp", "verify", "private", "fresh-context"):
        assert enforce.decide(P("route: " + tag + "\n" + HEAVY), {})["action"] == "allow"
    assert enforce.decide(P("route: build\n" + HEAVY), {})["action"] == "block"   # unknown route is not an exemption
