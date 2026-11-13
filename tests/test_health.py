import json
import time

from backbone import health


def _rec(p, usable, age=0):
    p.write_text(json.dumps({"saved_at": time.time() - age, "agents": [{"name": "codex", "usable": usable}]}))


def test_fresh_unusable_skipped(tmp_path):
    p = tmp_path / "d.json"
    _rec(p, False)
    assert not health.usable(str(p), "codex") and health.usable(str(p), "claude")


def test_stale_allowed(tmp_path):
    p = tmp_path / "d.json"
    _rec(p, False, age=99999)
    assert health.usable(str(p), "codex")


def test_missing_allowed(tmp_path):
    assert health.usable(str(tmp_path / "none.json"), "codex")


def test_save_roundtrip(tmp_path):
    p = tmp_path / "x" / "d.json"
    health.save(str(p), {"agents": [{"name": "codex", "usable": False}]})
    assert not health.usable(str(p), "codex")


def test_pick():
    assert health.pick(["claude", "codex"], lambda w: w == "codex") == "codex"
    assert health.pick(["claude", "codex"], lambda w: True) == "claude"
    assert health.pick(["claude", "codex"], lambda w: False) is None


def test_rewrite_gate(tmp_path):
    r = str(tmp_path)
    assert health.rewrite_gate(".venv/bin/python -m pytest -q", r) == r + "/.venv/bin/python -m pytest -q"
    assert health.rewrite_gate("./run.sh x", r) == r + "/run.sh x"
    assert health.rewrite_gate("pytest -q", r) == "pytest -q"
    assert health.rewrite_gate("", r) == ""
