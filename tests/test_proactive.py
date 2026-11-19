"""Proactive tick: isolated DB, fake bb, no network/model."""
import json
from types import SimpleNamespace

import pytest

from backbone import db, proactive

NOW = 1_800_000_000.0


def _deny(_):
    raise PermissionError("outside")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKBONE_PAUSE_FILES", "")
    (tmp_path / "src.md").write_text("x")
    bb = SimpleNamespace(con=db.connect(str(tmp_path / "r.db")), runs=SimpleNamespace(runs_dir=str(tmp_path / "runs")),
                         allowed=lambda: {"workers": {"nim1", "nim2"}}, cfg={}, guard_env={"BACKBONE_PAUSE_FILES": ""},
                         check_cwd=lambda c: c if c.startswith(str(tmp_path)) else _deny(c))
    mp = tmp_path / "manifest.json"

    def write(goals, **top):
        base = {"id": "a", "enabled": True, "priority": 1, "source_paths": ["src.md"], "prompt": "do it", "worker": "nim1"}
        mp.write_text(json.dumps({"version": 1, "goals": [{**base, **g} for g in goals], **top}))
        return mp
    return bb, write, tmp_path


def finish(bb, jid, state="done", result="ok"):
    bb.con.execute("UPDATE jobs SET state=?, result=? WHERE id=?", (state, result, jid))
    bb.con.commit()


def njobs(bb):
    return bb.con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def test_duplicate_tick_and_restart_recovery(env):
    bb, write, tmp = env
    mp = write([{}])
    assert proactive.tick(bb, mp, NOW)["status"] == "enqueued"
    assert proactive.tick(bb, mp, NOW)["reason"] == "max active"
    assert njobs(bb) == 1
    # crash between submit and state update: state wiped, job remains -> adopted, not duplicated
    bb.con.execute("UPDATE proactive_goals SET seq=0, active_job='', day_count=0")
    bb.con.commit()
    assert proactive.tick(bb, mp, NOW)["status"] == "wait"
    assert njobs(bb) == 1
    assert proactive.status(bb)["active"] == ["a"]
    opts = json.loads(bb.con.execute("SELECT opts FROM jobs").fetchone()[0])
    assert opts == {"worker": "nim1", "read_only": True, "escalate": "", "use_vault": False, "prepared": True}  # stays valid bb.run kwargs


def test_done_then_cooldown_then_next_seq_with_handoff(env):
    bb, write, tmp = env
    mp = write([{"cooldown_s": 100}])
    finish(bb, proactive.tick(bb, mp, NOW)["job"], "done", "result-text")
    assert proactive.tick(bb, mp, NOW + 10)["skipped"] == {"a": "cooldown"}
    h = json.loads((tmp / "runtime" / "a.json").read_text())
    assert h["outcome"] == "done" and h["snapshot_not_canonical"]
    r = proactive.tick(bb, mp, NOW + 200)
    assert r["status"] == "enqueued" and r["seq"] == 2
    text = bb.con.execute("SELECT text FROM jobs WHERE id=?", (r["job"],)).fetchone()[0]
    assert "result-text" in text and "src.md" in text


def test_blocked_falls_through_with_backoff(env):
    bb, write, tmp = env
    mp = write([{"id": "a", "priority": 1}, {"id": "b", "priority": 2}])
    finish(bb, proactive.tick(bb, mp, NOW)["job"], "blocked", "boom")
    r = proactive.tick(bb, mp, NOW + 1)
    assert r["goal"] == "b" and r["skipped"]["a"] == "cooldown"
    finish(bb, r["job"])
    assert proactive.tick(bb, mp, NOW + 2)["status"] == "wait"  # a backed off, b cooling: no retry storm


def test_offline_target(env):
    bb, write, _ = env
    mp = write([{"target": "mac2"}])
    assert proactive.tick(bb, mp, NOW, node_online=set())["skipped"] == {"a": "target offline"}
    assert proactive.tick(bb, mp, NOW, node_online=lambda t: t == "mac2")["status"] == "enqueued"
    assert bb.con.execute("SELECT target FROM jobs").fetchone()[0] == "mac2"


def test_pause_blocks_enqueue(env):
    bb, write, tmp = env
    p = tmp / "PAUSE"
    p.write_text("x")
    bb.guard_env = {"BACKBONE_PAUSE_FILES": str(p)}
    assert proactive.tick(bb, write([{}]), NOW)["status"] == "paused"
    assert njobs(bb) == 0


def test_caps(env):
    bb, write, _ = env
    mp = write([{"id": "a", "cooldown_s": 0, "daily_limit": 1}, {"id": "b", "priority": 2, "cooldown_s": 0}], daily_limit=2)
    finish(bb, proactive.tick(bb, mp, NOW)["job"])
    r = proactive.tick(bb, mp, NOW + 1)
    assert r["goal"] == "b" and r["skipped"]["a"] == "goal daily limit"
    finish(bb, r["job"])
    assert proactive.tick(bb, mp, NOW + 2) == {"status": "wait", "reason": "global daily limit"}
    assert proactive.tick(bb, mp, NOW + 90000)["status"] == "enqueued"  # next day


@pytest.mark.parametrize("bad", [{"id": "../x"}, {"id": "A b"}, {"worker": "rm"}, {"cwd": "/etc"},
                                 {"priority": "1"}, {"prompt": ""}, {"source_paths": "x"}, {"cooldown_s": -1}])
def test_malformed_rejected(env, bad):
    bb, write, _ = env
    assert proactive.tick(bb, write([bad]), NOW)["status"] == "invalid"
    assert njobs(bb) == 0


def test_duplicate_ids_rejected(env):
    bb, write, _ = env
    assert proactive.tick(bb, write([{}, {}]), NOW)["status"] == "invalid"


def test_missing_source_disabled_skip_independent_goal_runs(env):
    bb, write, _ = env
    mp = write([{"id": "a", "source_paths": ["nope.md"]}, {"id": "b", "enabled": False}, {"id": "c", "priority": 5}])
    r = proactive.tick(bb, mp, NOW)
    assert r["goal"] == "c" and r["skipped"] == {"a": "missing source", "b": "disabled"}


def test_active_goal_not_duplicated_with_parallel_capacity(env):
    bb, write, _ = env
    mp = write([{"id":"a"}, {"id":"b", "priority":2}], max_active=2)
    assert proactive.tick(bb, mp, NOW)["goal"] == "a"
    assert proactive.tick(bb, mp, NOW)["goal"] == "b"
    assert njobs(bb) == 2


def test_enqueue_crash_still_counts_against_budget(env):
    bb, write, _ = env
    mp = write([{}], daily_limit=1)
    jid = proactive.tick(bb, mp, NOW)["job"]
    bb.con.execute("UPDATE proactive_goals SET seq=0,active_job='',day_count=0")
    bb.con.commit()
    finish(bb, jid)
    assert proactive.tick(bb, mp, NOW+1)["reason"] == "global daily limit"


def test_host_load_gate(env, monkeypatch):
    bb, write, _ = env
    monkeypatch.setattr(proactive.os, "getloadavg", lambda: (5.0, 1.0, 1.0))
    assert proactive.tick(bb, write([{}], max_load=4), NOW)["reason"] == "host load"
    assert njobs(bb) == 0


def test_prepared_research_rejects_tools_gates_and_hooks():
    from backbone.guard import prepared_research
    opts=dict(worker="nim-chat:NIM_5", prepared=True, read_only=True, use_vault=False, escalate="")
    assert prepared_research(opts)
    for changed in ({"worker":"goose"},{"read_only":False},{"gate":"echo x"},{"use_vault":True},{"escalate":"codex"}):
        assert not prepared_research({**opts,**changed})
    assert not prepared_research(opts,{"hooks":{"pre_run":["anything"]}})


def test_bounded_feed_prefix_keeps_complete_records_only():
    raw = b'{"data":[{"title":"a"},{"title":"b"},{"title":"trunc'
    assert proactive.feed_prefix(raw) == [{"title":"a"},{"title":"b"}]
    with pytest.raises(ValueError): proactive.feed_prefix(b'{"data":[{"title":"trunc')


def test_new_source_wakes_goal_without_resetting_daily_budget(env):
    bb, write, tmp=env
    mp=write([{"cooldown_s":3600,"daily_limit":2}])
    jid=proactive.tick(bb,mp,NOW)["job"]; finish(bb,jid)
    assert proactive.tick(bb,mp,NOW+1)["reason"] == "nothing eligible"
    (tmp/'src.md').write_text('new evidence')
    assert proactive.tick(bb,mp,NOW+2)["seq"] == 2
    jid=bb.con.execute("SELECT active_job FROM proactive_goals").fetchone()[0]; finish(bb,jid)
    (tmp/'src.md').write_text('more evidence')
    assert proactive.tick(bb,mp,NOW+3)["skipped"]["a"] == "goal daily limit"


def test_lost_node_expires_and_other_goal_proceeds(env):
    bb,write,_=env
    mp=write([{"id":"a","target":"mac"},{"id":"b","priority":2}])
    first=proactive.tick(bb,mp,NOW,node_online={'mac'})
    bb.con.execute("UPDATE jobs SET updated=? WHERE id=?",(NOW,first['job']));bb.con.commit()
    result=proactive.tick(bb,mp,NOW+301,node_online=set())
    assert result['goal'] == 'b'
    assert bb.con.execute("SELECT state FROM jobs WHERE id=?",(first['job'],)).fetchone()['state'] == 'blocked'


def test_progress_without_required_artifact_is_blocked(env):
    bb,write,_=env
    mp=write([{'id':'a','require_artifact':True},{'id':'b','priority':2}])
    first=proactive.tick(bb,mp,NOW)
    finish(bb,first['job'],result='RESULT: progress\nNo draft yet')
    assert proactive.tick(bb,mp,NOW+1)['goal']=='b'
    assert bb.con.execute("SELECT last_outcome FROM proactive_goals WHERE goal_id='a'").fetchone()[0]=='blocked'
