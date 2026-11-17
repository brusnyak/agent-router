import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

from backbone.db import connect
from backbone.diagnose import diagnose, recover
from backbone.jobs import Jobs


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ROUTER_HOME", str(tmp_path))
    con = connect(str(tmp_path / "data/backbone.db"))
    return con, Jobs(SimpleNamespace(con=con)), tmp_path


def test_reason_codes_and_boundaries(queue):
    con, jobs, home = queue
    stuck = jobs.submit("expired")
    stale = jobs.submit("waiting", worker="missing")
    repeated = jobs.submit("failed")
    con.execute("UPDATE jobs SET state='running', lease_until=99 WHERE id=?", (stuck,))
    con.execute("UPDATE jobs SET created=-1801 WHERE id=?", (stale,))
    con.execute("UPDATE jobs SET attempts=3 WHERE id=?", (repeated,))
    work = home / "data/work/old"
    work.mkdir(parents=True)
    os.utime(work, (0, 0))
    results = diagnose(con, now=22000, home=home, agents={})
    reasons = {(r.get("id"), r["reason"]) for r in results}
    assert (stuck, "STUCK_RUNNING") in reasons
    assert (stale, "STALE_QUEUED") in reasons
    assert (stale, "NO_WORKER") in reasons
    assert (repeated, "REPEATED_FAILURE") in reasons
    assert (None, "ORPHAN_WORKTREE") in reasons
    con.execute("UPDATE jobs SET created=?, lease_until=?", (100, 1900))
    results = diagnose(con, now=1900, home=home, agents={"missing": "/stub"})
    assert not any(r["reason"] in ("STUCK_RUNNING", "STALE_QUEUED", "NO_WORKER") for r in results)


def test_dry_run_apply_and_attempt_cap(queue):
    con, jobs, home = queue
    ids = [jobs.submit(state) for state in ("running", "done", "blocked", "pending", "running")]
    for jid, state in zip(ids, ("running", "done", "blocked", "pending", "running")):
        con.execute("UPDATE jobs SET state=?, attempts=?, lease_until=10 WHERE id=?",
                    (state, 3 if jid == ids[-1] else 1, jid))
    con.commit()
    before = [tuple(r) for r in con.execute("SELECT * FROM jobs ORDER BY id")]
    assert len(recover(con, now=20)) == 1
    assert before == [tuple(r) for r in con.execute("SELECT * FROM jobs ORDER BY id")]
    assert not (home / "data/recover.log").exists()
    actions = recover(con, now=20, apply=True)
    assert len(actions) == 1 and actions[0]["id"] == ids[0]
    row = con.execute("SELECT * FROM jobs WHERE id=?", (ids[0],)).fetchone()
    assert row["state"] == "pending" and row["attempts"] == 2 and row["lease_until"] is None
    assert len(recover(con, now=20, apply=True)) == 0
    after = [tuple(r) for r in con.execute("SELECT * FROM jobs ORDER BY id") if r["id"] != ids[0]]
    assert after == [r for r in before if r[0] != ids[0]]
    audit = json.loads((home / "data/recover.log").read_text())
    assert audit["id"] == ids[0] and audit["new_attempt"] == 2


def test_singular_attempt_queued_schema(tmp_path):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE jobs(id, state, attempt, lease_until, created, updated, worker)")
    con.execute("INSERT INTO jobs VALUES ('job', 'running', 2, 10, 0, 0, '')")
    recover(con, now=20, apply=True, home=tmp_path)
    assert con.execute("SELECT state, attempt, lease_until FROM jobs").fetchone() == ("queued", 3, None)


def test_renewal_wins_over_recovery(queue, monkeypatch):
    from backbone import diagnose as module
    con, jobs, _ = queue
    jid = jobs.submit("renewed")
    con.execute("UPDATE jobs SET state='running', lease_until=10 WHERE id=?", (jid,))
    scan = module.diagnose
    def renewed(*args, **kwargs):
        findings = scan(*args, **kwargs)
        con.execute("UPDATE jobs SET lease_until=100 WHERE id=?", (jid,))
        return findings
    monkeypatch.setattr(module, "diagnose", renewed)
    assert recover(con, now=20, apply=True) == []
    assert con.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()[0] == "running"


def test_cli_lazy_and_read_only(queue, monkeypatch, capsys):
    from backbone import cli, discover
    con, jobs, home = queue
    jobs.submit("waiting")
    monkeypatch.setattr(discover, "discover", lambda: {"agents": {}})
    monkeypatch.setattr(cli, "Backbone", lambda: pytest.fail("must not initialize Backbone"))
    for command in ("diagnose", "recover"):
        with pytest.raises(SystemExit) as result:
            cli.main([command, "--json"])
        assert result.value.code == 0
        assert isinstance(json.loads(capsys.readouterr().out), list)
    assert not (home / "data/recover.log").exists()
