"""Tests for backbone.notify (no-cred no-op, never raises) and backbone.jobs (submit/list on a temp sqlite db)."""
import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backbone.db import connect
from backbone.jobs import Jobs
from backbone.notify import notify


def test_notify_no_creds_returns_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notify("anything") is False


def test_notify_never_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    def boom(*a, **k):
        raise OSError("no network")

    with patch("backbone.notify.urllib.request.urlopen", side_effect=boom):
        assert notify("hello") is False


def test_notify_non_200_returns_false(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    class Resp:
        status = 500

    with patch("backbone.notify.urllib.request.urlopen", return_value=Resp()):
        assert notify("hello") is False


def test_notify_ok_200_returns_true(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    class Resp:
        status = 200

    with patch("backbone.notify.urllib.request.urlopen", return_value=Resp()):
        assert notify("hello") is True


def _make_jobs(tmp_path):
    con = connect(str(tmp_path / "jobs.db"))
    bb = types.SimpleNamespace(con=con)
    return Jobs(bb)


def test_jobs_submit_and_list(tmp_path):
    jobs = _make_jobs(tmp_path)
    jid = jobs.submit("run the pipeline", project="hermes-ui", worker="nim1")
    assert isinstance(jid, str) and len(jid) == 8
    rows = jobs.list()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == jid
    assert row["state"] == "pending"
    assert row["attempts"] == 0
    assert row["text"] == "run the pipeline"


def test_jobs_list_most_recent_first_with_limit(tmp_path):
    jobs = _make_jobs(tmp_path)
    ids = [jobs.submit(f"job {i}") for i in range(5)]
    rows = jobs.list(limit=2)
    assert len(rows) == 2
    assert rows[0]["id"] == ids[-1]
    assert rows[1]["id"] == ids[-2]
    assert all(r["state"] == "pending" for r in rows)


def test_jobs_submit_persists_across_instances(tmp_path):
    con = connect(str(tmp_path / "jobs.db"))
    Jobs(types.SimpleNamespace(con=con)).submit("first job")
    rows = Jobs(types.SimpleNamespace(con=con)).list()
    assert len(rows) == 1
    assert rows[0]["text"] == "first job"


def test_hub_run_accepts_named_gate_job(tmp_path):
    """A job submitted with a named gate carries gate_name for nodes; the hub's own bb.run must not receive it (it raised TypeError,
    the job went 'blocked' with no error: Nina's `router vm --gate pytest` never ran)."""
    con = connect(str(tmp_path / "jobs.db"))
    seen = {}

    class BB:
        def __init__(self):
            self.con = con
            self.runs = types.SimpleNamespace(get=lambda r: None)

        def run(self, text, on_start=None, gate=None, **kw):  # real signature has no gate_name
            seen.update(text=text, gate=gate, kw=kw)
            return {"state": "done", "run": "r1"}

    jobs = Jobs(BB())
    jid = jobs.submit("do it", gate="true", gate_name="noop")
    job = jobs._claim()
    jobs._execute(job)
    row = [r for r in jobs.list() if r["id"] == jid][0]
    assert row["state"] == "done" and seen["gate"] == "true" and "gate_name" not in seen["kw"]


def test_execute_persists_result_for_next_operator(tmp_path):
    jobs = _make_jobs(tmp_path)
    jobs.bb.runs = types.SimpleNamespace(get=lambda rid: None)
    jobs.bb.run = lambda text, **opts: {"state":"done", "run":"r1", "output":"verified receipt"}
    jid = jobs.submit("bounded goal")
    job = dict(jobs.con.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
    with patch("backbone.jobs.notify"):
        jobs._execute(job)
    assert jobs.get(jid)["result"] == "verified receipt"


def test_interactive_daemon_leaves_prepared_research_for_bounded_executor(tmp_path):
    jobs = _make_jobs(tmp_path)
    jobs.bb.cfg = {"db":str(tmp_path/'jobs.db')}
    jobs.bb.guard_env = {"BACKBONE_UNATTENDED":"0", "BACKBONE_PAUSE_FILES":""}
    jobs.submit("research", worker="nim-chat:NIM_5", read_only=True, prepared=True, use_vault=False, escalate="")
    other=jobs.submit("interactive", worker="goose")
    assert jobs._claim()["id"] == other


def test_unattended_executor_leaves_generic_jobs(tmp_path):
    jobs = _make_jobs(tmp_path)
    jobs.bb.cfg = {"db":str(tmp_path/'jobs.db')}
    jobs.bb.guard_env = {"BACKBONE_UNATTENDED":"1", "BACKBONE_PAUSE_FILES":""}
    jobs.submit("generic", worker="goose")
    research=jobs.submit("research", worker="nim-chat:NIM_5", read_only=True, prepared=True, use_vault=False, escalate="")
    assert jobs._claim()["id"] == research
