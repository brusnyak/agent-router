"""Self-scan install: all writes happen under a temporary HOME."""
import json

import pytest

from backbone import harness as h
from backbone import scan


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AGENT_ROUTER_HOME", str(tmp_path / "router"))
    return tmp_path


def client(home, name, rules=None, hooks=None):
    d = home / name
    d.mkdir(exist_ok=True)
    if rules:
        (d / rules).write_text("mine\n")
    if hooks is not None:
        (d / "settings.json").write_text(json.dumps({"hooks": hooks, "x": 1}))
    return d


def test_scan_finds_unknown_client_by_contents(home):
    client(home, ".newagent", rules="AGENTS.md")
    client(home, ".hooky", hooks={})
    (home / ".empty").mkdir()
    ids = {c["id"]: c for c in scan.scan(home)}
    assert set(ids) == {"newagent", "hooky"} and ids["hooky"]["hooks"] and not ids["newagent"]["hooks"]


def test_plan_apply_idempotent_and_uninstall(home):
    d = client(home, ".newagent", rules="AGENTS.md", hooks={})
    changes = scan.plan(home)
    assert {p.name for p, _, _ in changes} == {"AGENTS.md", "settings.json"}
    for p, o, n in changes:
        h._write(p, o, n)
    s = json.loads((d / "settings.json").read_text())
    assert s["x"] == 1 and len(s["hooks"]["UserPromptSubmit"]) == 1 and s["hooks"]["PreToolUse"][0]["matcher"] == "Agent|Task"
    assert h.BEGIN in (d / "AGENTS.md").read_text() and (d / "AGENTS.md").read_text().startswith("mine")
    assert scan.plan(home) == []                                   # second run: nothing to do
    for p, o, n in scan.plan(home, remove=True):
        h._write(p, o, n)
    assert json.loads((d / "settings.json").read_text())["hooks"] == {}
    assert (d / "AGENTS.md").read_text() == "mine\n"


def test_hand_installed_hook_is_replaced_by_managed_entry(home):
    other = {"hooks": [{"type": "command", "command": "keep-me"}]}
    for cmd in ("PYTHONPATH=/r python3 -m backbone.hook", "/py /r/backbone/hook.py"):
        manual = {"hooks": [{"type": "command", "command": cmd}]}
        d = client(home, ".c" + str(abs(hash(cmd)) % 99), hooks={"UserPromptSubmit": [other, manual]})
        new = json.loads(scan.merge_hooks((d / "settings.json").read_text(), scan.hook_entries()))
        rows = new["hooks"]["UserPromptSubmit"]
        assert rows[0] == other and len(rows) == 2 and scan.MARK in rows[1]["hooks"][0]["command"]
        gone = json.loads(scan.merge_hooks(json.dumps(new), scan.hook_entries(), remove=True))
        assert gone["hooks"]["UserPromptSubmit"] == [other]


def test_foreign_hook_schema_is_not_touched(home):
    client(home, ".gem", rules="GEMINI.md", hooks={"BeforeTool": []})
    c = scan.scan(home)[0]
    assert c["rules"] and not c["hooks"] and c["settings"] is None
