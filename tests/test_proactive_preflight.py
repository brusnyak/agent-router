import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('preflight', Path(__file__).parents[1] / 'scripts/proactive_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def runtime(tmp_path):
    from backbone.proactive import SCHEMA
    from backbone.db import SCHEMA as DB_SCHEMA
    db = tmp_path / 'backbone.db'
    con = sqlite3.connect(str(db))
    con.executescript(DB_SCHEMA)
    con.execute(SCHEMA)
    con.execute('CREATE TABLE IF NOT EXISTS nodes(name TEXT,last_seen REAL,caps TEXT)')
    day = '2026-11-19'
    con.execute('INSERT INTO proactive_goals(goal_id,seq,day,day_count) VALUES (?,?,?,?)', ('career', 8, day, 8))
    con.commit()
    con.close()
    (tmp_path / 'source.md').write_text('Generic public source')
    goal = dict(id='career', priority=1, enabled=True, worker='nim-chat:TEST', source_paths=['source.md'], daily_limit=8, prompt='Read generic evidence')
    manifest = tmp_path / 'goals.json'
    manifest.write_text(json.dumps(dict(version=1, daily_limit=8, goals=[goal])))
    import time
    now = time.mktime(time.strptime(day, '%Y-%m-%d')) + 3600
    return manifest, {'db': str(db)}, now


def test_exhausted_budget_explains_unchanged_seq_without_writes(runtime):
    path, cfg, now = runtime
    before = {p.name: p.read_bytes() for p in path.parent.iterdir()}
    result = preflight.inspect(path, cfg, env={}, now=now)
    assert result['global_used'] == result['global_limit'] == 8
    assert result['goals'][0]['scheduler'] == 'global daily limit'
    assert result['goals'][0]['seq'] == 8
    assert {p.name: p.read_bytes() for p in path.parent.iterdir()} == before


def test_pause_missing_source_and_unknown_health(runtime):
    path, cfg, now = runtime
    pause = path.parent / 'PAUSE'
    pause.touch()
    (path.parent / 'source.md').unlink()
    result = preflight.inspect(path, cfg, env={'BACKBONE_PAUSE_FILES': str(pause)}, now=now)
    row = result['goals'][0]
    assert row['scheduler'] == 'paused'
    assert row['missing_sources'] == ['source.md']
    assert row['worker_health'] == 'unknown'
    assert row['dispatch_guard'].startswith('paused:')


def test_unattended_missing_ledger_fails_closed(runtime):
    path, cfg, now = runtime
    row = preflight.inspect(path, cfg, env={'BACKBONE_UNATTENDED': '1'}, now=now)['goals'][0]
    assert row['dispatch_guard'] == 'budget: ledger unavailable'


def test_missing_database_never_created(tmp_path):
    path = tmp_path / 'absent.db'
    with pytest.raises(sqlite3.OperationalError):
        preflight.read_db(path)
    assert not path.exists()


def test_guard_budget_and_cached_worker_health(runtime):
    path, cfg, now = runtime
    day = '2026-11-19'
    con = sqlite3.connect(path.parent / 'ledger.db')
    con.execute('CREATE TABLE calls(ts REAL,day TEXT,worker TEXT,ok INTEGER,cost REAL)')
    con.execute('INSERT INTO calls VALUES (?,?,?,?,?)', (now, day, 'nim-chat', 1, 0))
    con.commit()
    con.close()
    doctor = path.parent / 'doctor.json'
    doctor.write_text(json.dumps({'saved_at': now, 'agents': [{'name': 'nim-chat', 'usable': False}]}))
    env = {'BACKBONE_UNATTENDED': '1', 'BACKBONE_BUDGET_CALLS': '1'}
    row = preflight.inspect(path, cfg, env=env, now=now, doctor_path=doctor)['goals'][0]
    assert row['dispatch_guard'] == 'budget: 1 calls today >= cap 1'
    assert row['worker_health'] == 'cached unusable'
    row = preflight.inspect(path, cfg, env=env, now=now + 21601, doctor_path=doctor)['goals'][0]
    assert row['worker_health'] == 'unknown'


@pytest.mark.parametrize('case,expected', [
    ('global', 'global daily limit'), ('disabled', 'disabled'),
    ('missing', 'missing source'), ('cooldown', 'cooldown'),
    ('goal_budget', 'goal daily limit'), ('load', 'host load'),
])
def test_scheduler_blocker_matches_actual_tick_branch_order(runtime, monkeypatch, case, expected):
    """Run real scheduler against isolated fixture DB; no worker dispatch."""
    from backbone import proactive, db
    from types import SimpleNamespace
    path, cfg, now = runtime
    manifest = json.loads(path.read_text())
    goal = manifest['goals'][0]
    # Several blockers coexist; compare with executor ordering rather than
    # assuming the most specific-looking reason takes precedence.
    if case != 'global': manifest['daily_limit'] = 100
    if case == 'disabled': goal['enabled'] = False
    if case in ('global', 'disabled', 'missing'): (path.parent / 'source.md').unlink()
    manifest['max_load'] = 4
    path.write_text(json.dumps(manifest))
    con = sqlite3.connect(cfg['db'])
    con.row_factory = sqlite3.Row
    if case in ('global', 'disabled', 'missing', 'cooldown'):
        con.execute('UPDATE proactive_goals SET next_due=?', (now + 500,))
        con.commit()
    load = 5 if case == 'load' else 0
    monkeypatch.setattr(proactive.os, 'getloadavg', lambda: (load, 0, 0))
    monkeypatch.setenv('BACKBONE_PAUSE_FILES', '')
    env = {'BACKBONE_PAUSE_FILES': ''}
    bb = SimpleNamespace(con=con, cfg=cfg, guard_env=env,
                         runs=SimpleNamespace(runs_dir=str(path.parent / 'runs')),
                         allowed=lambda: {'workers': {'nim-chat:TEST'}})
    try:
        snapshot = preflight.inspect(path, cfg, env=env, now=now, load=load)
        actual = proactive.tick(bb, path, now=now)
        actual_reason = actual.get('skipped', {}).get('career', actual.get('reason'))
        assert snapshot['goals'][0]['scheduler'] == actual_reason == expected
        assert con.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    finally:
        con.close()


@pytest.mark.parametrize('zone', ['UTC', 'America/New_York'])
def test_budget_day_matches_scheduler_host_timezone(runtime, monkeypatch, zone):
    import calendar
    import os
    import time
    from backbone.proactive import _day
    if not hasattr(time, 'tzset'): pytest.skip('host timezone control unavailable')
    path, cfg, _ = runtime
    previous = os.environ.get('TZ')
    try:
        monkeypatch.setenv('TZ', zone)
        time.tzset()
        now = calendar.timegm((2026, 11, 19, 0, 30, 0))
        with sqlite3.connect(cfg['db']) as con:
            con.execute('UPDATE proactive_goals SET day=?', (_day(now),))
        snapshot = preflight.inspect(path, cfg, env={}, now=now)
        assert snapshot['day'] == _day(now)
        assert snapshot['day'] == ('2026-11-19' if zone == 'UTC' else '2026-11-18')
        assert snapshot['global_used'] == 8
    finally:
        if previous is None: os.environ.pop('TZ', None)
        else: os.environ['TZ'] = previous
        time.tzset()
