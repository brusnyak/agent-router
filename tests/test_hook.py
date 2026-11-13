import json
import os
import subprocess
import sys

from backbone.hook import decide, fnv1a32

P = "please refactor this module now"


def test_machine_turn():
    for p in ("Another Claude session sent x", "<task-notification>y"):
        r = decide({"prompt": p, "session_id": "s", "prompt_id": "p"})
        assert r["mode"] == "machine-turn" and r["arm"] is None


def test_lane_child(monkeypatch):
    monkeypatch.setenv("MR_ORCH_DISPATCH", "1")
    assert decide({"prompt": P, "session_id": "s"})["mode"] == "lane-child"


def test_too_short(monkeypatch):
    monkeypatch.delenv("MR_ORCH_DISPATCH", raising=False)
    assert decide({"prompt": "hi", "session_id": "s"})["mode"] == "too-short"


def test_arm_deterministic(monkeypatch):
    monkeypatch.delenv("MR_ORCH_DISPATCH", raising=False)
    sid = "session-abc"
    want = "holdout" if fnv1a32(sid) % 100 < 20 else "treat"
    assert decide({"prompt": P, "session_id": sid})["arm"] == want
    assert decide({"prompt": P, "session_id": sid})["arm"] == want
    assert decide({"prompt": P})["arm"] == "none"


def test_holdout_zero(monkeypatch):
    monkeypatch.delenv("MR_ORCH_DISPATCH", raising=False)
    for i in range(200):
        assert decide({"prompt": P, "session_id": f"s{i}"}, holdout_pct=0)["arm"] == "treat"


def test_no_raw_prompt():
    secret = "SECRET-PROMPT-TEXT-123"
    r = decide({"prompt": secret, "session_id": "s", "prompt_id": "p"})
    assert secret not in json.dumps(r) and len(r["prompt_hash"]) == 64


def test_malformed_stdin(tmp_path):
    log = tmp_path / "log.jsonl"
    env = {**os.environ, "HOOK_LOG": str(log)}
    p = subprocess.run([sys.executable, "-m", "backbone.hook"], input="{not json",
                       capture_output=True, text=True, env=env, timeout=10)
    assert p.returncode == 0 and p.stdout == "" and not log.exists()
