"""require_source_change: isolated SQLite, no network/model."""
from types import SimpleNamespace

import pytest
from backbone import db, proactive
from backbone.jobs import Jobs
from tests.test_proactive import env, finish, njobs, NOW  # noqa: F401

DAY = 86400


def test_unchanged_after_success_restart_and_day_rollover(env):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 0, "daily_limit": 9}], daily_limit=50)
    finish(bb, proactive.tick(bb, mp, NOW)["job"])
    for t in (NOW + 10, NOW + 3 * DAY):  # each tick is stateless: all state lives in SQLite
        r = proactive.tick(bb, mp, t)
        assert r["status"] == "wait" and r["reason"] == "unchanged evidence"
    assert njobs(bb) == 1


def test_changed_source_one_enqueue(env):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 0}])
    finish(bb, proactive.tick(bb, mp, NOW)["job"])
    (tmp / "src.md").write_text("changed")
    assert proactive.tick(bb, mp, NOW + 5)["status"] == "enqueued"
    assert proactive.tick(bb, mp, NOW + 6)["reason"] == "max active"
    assert njobs(bb) == 2


def test_failure_does_not_consume_input(env):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 100}])
    finish(bb, proactive.tick(bb, mp, NOW)["job"], "blocked", "fail")
    # Failure is reconciled at NOW+50: next_due = NOW+50 + 2*max(cooldown,60) = NOW+250.
    assert proactive.tick(bb, mp, NOW + 50)["skipped"]["a"] == "cooldown"
    assert proactive.tick(bb, mp, NOW + 249)["skipped"]["a"] == "cooldown"
    assert proactive.tick(bb, mp, NOW + 251)["status"] == "enqueued"
    assert njobs(bb) == 2


def test_unchanged_success_survives_restart_on_separate_connection(env):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 0, "daily_limit": 9}], daily_limit=50)
    finish(bb, proactive.tick(bb, mp, NOW)["job"])  # successful run consumes the input digest
    getattr(bb.con, "_c", bb.con).close()  # close wrapper/native fixture connection; reload persisted state
    bb = SimpleNamespace(**{**vars(bb), "con": db.connect(str(tmp / "r.db"))})
    for t in (NOW + 10, NOW + 3 * DAY):  # fresh connection, then a day rollover
        r = proactive.tick(bb, mp, t)
        assert r["status"] == "wait" and r["reason"] == "unchanged evidence"
    assert njobs(bb) == 1


@pytest.mark.parametrize("extra", [{"require_source_change": "yes"}, {"require_source_change": 1},
                                   {"require_source_change": True, "read_only": False},
                                   {"require_source_change": True, "worker": "career-scan:idle"},
                                   {"require_source_change": True, "feeds": ["arbeitnow"]}])
def test_invalid_combinations_rejected(env, extra):
    bb, write, tmp = env
    bb.allowed = lambda: {"workers": {"nim1", "career-scan:idle"}}
    assert proactive.tick(bb, write([extra]), NOW)["status"] == "invalid"


def test_pause_and_global_budget_dominate(env):
    bb, write, tmp = env
    mp = write([{"require_source_change": True}])
    flag = tmp / "PAUSE"
    flag.write_text("x")
    bb.guard_env = {"BACKBONE_PAUSE_FILES": str(flag)}
    assert proactive.tick(bb, mp, NOW)["status"] == "paused" and njobs(bb) == 0
    bb.guard_env = {"BACKBONE_PAUSE_FILES": ""}
    mp = write([{"require_source_change": True}], daily_limit=0)
    assert proactive.tick(bb, mp, NOW)["reason"] == "global daily limit" and njobs(bb) == 0


def test_source_mutation_inside_submit_is_not_consumed(env, monkeypatch):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 0}])
    real_submit = Jobs.submit

    def mutating_submit(self, *a, **kw):  # source changes after context was built, before the job is recorded
        (tmp / "src.md").write_text("changed")
        return real_submit(self, *a, **kw)

    monkeypatch.setattr(Jobs, "submit", mutating_submit)
    jid = proactive.tick(bb, mp, NOW)["job"]
    monkeypatch.setattr(Jobs, "submit", real_submit)
    finish(bb, jid)  # first job built from the original input; must not consume the changed input
    assert proactive.tick(bb, mp, NOW + 5)["status"] == "enqueued"
    assert njobs(bb) == 2


def test_mutation_while_source_context_reads_skips_submit(env, monkeypatch):
    bb, write, tmp = env
    mp = write([{"require_source_change": True, "cooldown_s": 0}])
    real_context = proactive._source_context

    def mutating_context(g, base):  # source changes while it is being read
        text = real_context(g, base)
        (tmp / "src.md").write_text("changed")
        return text

    monkeypatch.setattr(proactive, "_source_context", mutating_context)
    r = proactive.tick(bb, mp, NOW)
    assert r["status"] == "wait" and r["reason"] == "input changed during read"
    assert r["skipped"]["a"] == "input changed"
    assert njobs(bb) == 0  # no submit happened
    monkeypatch.setattr(proactive, "_source_context", real_context)
    assert proactive.tick(bb, mp, NOW + 5)["status"] == "enqueued"
    assert njobs(bb) == 1
