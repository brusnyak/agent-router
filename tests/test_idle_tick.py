"""Idle tick: submit next backlog item when idle; honour PAUSE; flock-safe; idempotent."""
import json
import time

from backbone.core import Backbone
from backbone import idle_tick


def write_backlog(tmp_path, items):
    p = tmp_path / "backlog.jsonl"
    with open(p, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    return p


def test_empty_backlog_returns_empty(tmp_path, monkeypatch):
    bb = _bb(tmp_path, monkeypatch)
    res = idle_tick.tick({}, backlog_path=str(tmp_path / "empty.jsonl"), bb=bb)
    assert res["state"] == "empty"


def test_submits_first_item_and_consumes_it(tmp_path, monkeypatch):
    p = write_backlog(tmp_path, [
        {"prompt": "do one", "worker_hint": "nim1", "gate": "compile"},
        {"prompt": "do two", "runner": "mac"},
    ])
    bb = _bb(tmp_path, monkeypatch)
    res = idle_tick.tick({}, backlog_path=str(p), bb=bb)
    assert res["state"] == "submitted", res
    assert res["item"]["prompt"] == "do one"
    assert res["job"]
    remaining = idle_tick.read_backlog(str(p))
    assert [it["prompt"] for it in remaining] == ["do two"]


def test_mac_runner_addressed_to_node_mac(tmp_path, monkeypatch):
    p = write_backlog(tmp_path, [{"prompt": "build it", "runner": "mac"}])
    bb = _bb(tmp_path, monkeypatch)
    res = idle_tick.tick({}, backlog_path=str(p), bb=bb)
    assert res["state"] == "submitted"
    row = bb.con.execute("SELECT text,target FROM jobs WHERE id=?", (res["job"],)).fetchone()
    assert row["text"] == "build it" and row["target"] == "mac"


def test_honours_pause_file(tmp_path, monkeypatch):
    pause = tmp_path / "dispatch-PAUSE"
    pause.write_text("")
    p = write_backlog(tmp_path, [{"prompt": "do one"}])
    bb = _bb(tmp_path, monkeypatch)
    res = idle_tick.tick({}, pause_file=str(pause), backlog_path=str(p), bb=bb)
    assert res["state"] == "paused"
    assert idle_tick.read_backlog(str(p))  # nothing consumed


def test_recent_job_running_means_active(tmp_path, monkeypatch):
    bb = _bb(tmp_path, monkeypatch)
    now = time.time()
    bb.con.execute("INSERT INTO jobs(id,text,opts,state,owner,created,updated) VALUES(?,?,?,?,?,?,?)",
                   ("j1", "x", "{}", "running", "daemon", now, now))
    bb.con.commit()
    p = write_backlog(tmp_path, [{"prompt": "do one"}])
    res = idle_tick.tick({}, backlog_path=str(p), bb=bb, idle_minutes_override=10)
    assert res["state"] == "active"
    assert idle_tick.read_backlog(str(p))


def test_recently_updated_job_means_active(tmp_path, monkeypatch):
    bb = _bb(tmp_path, monkeypatch)
    now = time.time()
    bb.con.execute("INSERT INTO jobs(id,text,opts,state,owner,created,updated) VALUES(?,?,?,?,?,?,?)",
                   ("j1", "x", "{}", "done", "daemon", now - 300, now - 300))
    bb.con.commit()
    p = write_backlog(tmp_path, [{"prompt": "do one"}])
    res = idle_tick.tick({}, backlog_path=str(p), bb=bb, idle_minutes_override=10)
    assert res["state"] == "active"


def test_idle_enough_after_window_expires(tmp_path, monkeypatch):
    bb = _bb(tmp_path, monkeypatch)
    now = time.time()
    old = now - 900  # 15 min ago
    bb.con.execute("INSERT INTO jobs(id,text,opts,state,owner,created,updated) VALUES(?,?,?,?,?,?,?)",
                   ("j1", "x", "{}", "done", "daemon", old, old))
    bb.con.commit()
    p = write_backlog(tmp_path, [{"prompt": "do one"}])
    res = idle_tick.tick({}, backlog_path=str(p), bb=bb, idle_minutes_override=10)
    assert res["state"] == "submitted"


def test_flock_serializes_concurrent_ticks(tmp_path, monkeypatch):
    import fcntl
    bb = _bb(tmp_path, monkeypatch)
    p = write_backlog(tmp_path, [{"prompt": "do one"}])
    lock = str(tmp_path / "idle_tick.lock")
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        res = idle_tick.tick({}, backlog_path=str(p), lock_path=lock, bb=bb)
        assert res["state"] == "busy"
        fcntl.flock(fh, fcntl.LOCK_UN)
    res = idle_tick.tick({}, backlog_path=str(p), lock_path=lock, bb=bb)
    assert res["state"] == "submitted"


def _bb(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKBONE_NO_SECRETS_FILE", "1")
    cfg = {
        "db": str(tmp_path / "bb.db"),
        "tickets_dir": str(tmp_path / "tickets"),
        "runs_dir": str(tmp_path / "runs"),
        "work_dir": str(tmp_path / "work"),
        "context": {"budget_tokens": 600, "summarize_over_tokens": 150, "keep_recent_turns": 2,
                    "vault_query": "/nonexistent"},
        "guard": {},
        "understand": False,
        "critic": {"when": "never"},
        "nim": {"keys": ["NIM_1", "NIM_2", "NIM_3"], "default_key": "NIM_1", "rpm_limit": 40,
                "cooldown_s": 0, "wait_s": 120, "max_concurrent_per_key": 0, "base_url": "x",
                "model": "nvidia/nemotron-3.5-super-vl-120b-a12b"},
        "workers": {},
    }
    bb = Backbone(cfg, env={"NIM_1": "a", "NIM_2": "b", "NIM_3": "c"})
    return bb


def test_cli_idle_tick_smoke(tmp_path):
    """The CLI entry must run end to end (regression: UnboundLocalError on load_config)."""
    import os, subprocess, sys
    env = {**os.environ, "HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "backbone", "idle-tick"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-400:]
