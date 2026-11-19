"""Offline safety gates: temporary state only; no keys, sends, workers or network."""
import concurrent.futures
import csv
import datetime as dt
import fcntl
import json
from pathlib import Path
import plistlib
import sys
from types import SimpleNamespace

import pytest
import yaml
from backbone import guard, night
from backbone.core import Backbone
from backbone.jobs import Jobs

PAYLOAD = Path(__file__).resolve().parent / 'fixtures'
NOW = dt.datetime(2026, 11, 18, 23, 0, tzinfo=night.TZ)


@pytest.fixture
def queue(tmp_path):
    path = tmp_path / 'night/tasks.yaml'
    path.parent.mkdir()
    path.write_text((PAYLOAD / 'night/tasks.yaml').read_text())
    return path


def env(tmp_path):
    return {'BACKBONE_PAUSE_FILES': str(tmp_path / 'PAUSE')}


def test_atomic_does_not_follow_leftover_temp_symlink(tmp_path):
    outside = tmp_path / 'source.csv'
    outside.write_text('preserve source')
    out = tmp_path / 'out'
    out.mkdir()
    target = out / 'state.json'
    (out / 'state.json.tmp').symlink_to(outside)
    night.atomic(target, 'new state')
    assert outside.read_text() == 'preserve source'
    assert target.read_text() == 'new state'
    assert sorted(p.name for p in out.iterdir()) == ['state.json', 'state.json.tmp']


def test_pause_no_state_no_execution(queue, tmp_path, monkeypatch):
    pause = tmp_path / 'PAUSE'
    pause.write_text('hold')
    monkeypatch.setattr(night, 'execute', lambda *a: pytest.fail('executed while paused'))
    assert night.tick(queue, dry_run=True, env=env(tmp_path)) == {'state': 'halted', 'rc': 0, 'tasks_run': 0}
    assert not (queue.parent / 'dry-run/state.json').exists()


def test_dry_run_exactly_one_task_and_separate_state(queue, tmp_path, monkeypatch):
    monkeypatch.setattr(night.subprocess, 'Popen', lambda *a, **k: pytest.fail('dry run spawned child'))
    result = night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)
    assert result['state'] == 'done' and result['tasks_run'] == 1
    state = json.loads(Path(result['state_path']).read_text())
    assert list(state['tasks']) == ['enrich-maps'] and len(state['history']) == 1
    assert not (queue.parent / 'state.json').exists()
    assert 'enrich-maps: done rc=0' in (queue.parent / 'dry-run/out/morning.md').read_text()
    assert night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)['id'] == 'enrich-realtors'


def test_complete_queue_and_no_replay(queue, tmp_path):
    results = [night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW) for _ in range(6)]
    assert [r.get('id') for r in results[:5]] == [t['id'] for t in night.load_queue(queue)]
    assert all(r['state'] == 'done' for r in results[:5])
    assert results[5]['state'] == 'complete' and results[5]['tasks_run'] == 0
    state = json.loads((queue.parent / 'dry-run/state.json').read_text())
    report = (queue.parent / 'dry-run/out/morning.md').read_text()
    assert len(state['history']) == 5 and report.count(': done rc=0 ') == 5


def test_two_failures_stop_persist_restart_and_max_two_retries(queue, tmp_path, monkeypatch):
    calls = []
    def fail(*a):
        calls.append(1)
        raise ValueError('fake failure')
    monkeypatch.setattr(night, 'execute', fail)
    for _ in range(2):
        assert night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)['state'] == 'failed'
    assert night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)['state'] == 'stopped-for-night'
    next_night = NOW + dt.timedelta(days=1)
    assert night.tick(queue, dry_run=True, env=env(tmp_path), now=next_night)['attempt'] == 3
    assert night.tick(queue, dry_run=True, env=env(tmp_path), now=next_night)['state'] == 'retry-exhausted'
    assert len(calls) == 3
    report = (queue.parent / 'dry-run/out/morning.md').read_text()
    assert report.count(': failed rc=1 ') == 3


def test_window_timezone_boundaries(queue, tmp_path):
    for hour, allowed in [(22, False), (23, True), (0, True), (6, True), (7, False)]:
        now = NOW.replace(hour=hour)
        assert night.in_window(now=now) is allowed
    assert not night.in_window(now=NOW.astimezone(dt.timezone.utc).replace(hour=6))  # 07:00 local
    result = night.tick(queue, env=env(tmp_path), now=NOW.replace(hour=12))
    assert result['state'] == 'out-of-window' and not (queue.parent / 'state.json').exists()


def test_single_instance(queue, tmp_path):
    root = queue.parent / 'dry-run'
    root.mkdir()
    with (root / 'tick.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)['state'] == 'busy'


def test_queue_change_fails_closed(queue, tmp_path):
    night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)
    queue.write_text(queue.read_text() + '\n# changed\n')
    with pytest.raises(ValueError, match='queue changed'):
        night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)


def test_escape_and_arbitrary_command_rejected(queue):
    tasks = yaml.safe_load(queue.read_text())
    tasks['tasks'][0]['output'] = '../../escape.csv'
    queue.write_text(yaml.safe_dump(tasks))
    with pytest.raises(ValueError, match='escapes'):
        night.load_queue(queue)
    tasks['tasks'][0].update(output='safe.csv', kind='shell')
    queue.write_text(yaml.safe_dump(tasks))
    with pytest.raises(ValueError, match='unsupported'):
        night.load_queue(queue)


def test_drafts_top5_csv_facts_only(queue, tmp_path):
    out = queue.parent / 'out'
    out.mkdir()
    data = [{'name': f'Lead {i}', 'site': f'https://example.invalid/{i}', 'status': 'READY',
             'sources': json.dumps({'site': [{'value': f'https://example.invalid/{i}', 'url': 'https://source.invalid'}]})}
            for i in range(7)]
    for name in ('maps-enriched.csv', 'realtors-enriched.csv'):
        with (out / name).open('w') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    task = night.load_queue(queue)[3]
    night.execute(task, queue, out, False, env(tmp_path))
    manifest = json.loads((out / task['output']).read_text())
    assert len(manifest['drafts']) == 10
    for path in manifest['drafts']:
        text = Path(path).read_text()
        assert 'DO NOT SEND' in text and 'https://example.invalid/' in text
        assert 'Lead 5' not in text and 'Lead 6' not in text


def test_plists_one_scheduler_no_keys_or_loop():
    for path in (PAYLOAD / 'LaunchAgents').glob('*.plist'):
        data = plistlib.loads(path.read_bytes())
        assert data['RunAtLoad'] is False and data['KeepAlive'] is False
        assert not any('KEY' in k or 'TOKEN' in k or k.startswith('NIM_') for k in data['EnvironmentVariables'])
        assert '--loop' not in data['ProgramArguments']
        assert data.get('StartInterval') == (900 if data['Label'].endswith('night-gate') else None)
        assert 'StartCalendarInterval' not in data


@pytest.mark.parametrize('value', ['bad', '-1', 'nan', 'inf'])
def test_invalid_budget_fails_closed(value, tmp_path):
    ledger = guard.Ledger(str(tmp_path / 'budget.db'))
    with pytest.raises(guard.Blocked, match='invalid'):
        guard.check('nim-chat', True, env={'BACKBONE_PAUSE_FILES': '', 'BACKBONE_BUDGET_USD': value}, ledger=ledger)


def test_zero_config_cap_and_missing_ledger_fail_closed():
    with pytest.raises(guard.Blocked, match='zero cap'):
        guard.check('nim-chat', True, cfg={'guard': {'calls_per_day': 0}}, env={'BACKBONE_PAUSE_FILES': ''})
    with pytest.raises(guard.Blocked, match='ledger unavailable'):
        guard.check('nim-chat', True, env={'BACKBONE_PAUSE_FILES': '', 'BACKBONE_UNATTENDED': '1'})


def test_atomic_budget_concurrent_reservations(tmp_path):
    db = str(tmp_path / 'ledger.db')
    guard.Ledger(db).con.close()
    def reserve(_):
        ledger = guard.Ledger(db)
        try:
            ledger.reserve('nim-chat', True, env={'BACKBONE_PAUSE_FILES': '', 'BACKBONE_BUDGET_CALLS': '3'})
            return 1
        except guard.Blocked:
            return 0
        finally:
            ledger.con.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(16))) == 3
    assert guard.Ledger(db).today()['nim-chat']['calls'] == 3


def test_exception_counts_dispatch_attempt(tmp_path, monkeypatch):
    bb = SimpleNamespace(cfg={'db': str(tmp_path / 'router.db')})
    def crash(*a):
        raise RuntimeError('fake worker crash')
    monkeypatch.setattr(Backbone, '_dispatch_raw', crash)
    with pytest.raises(RuntimeError):
        Backbone._dispatch(bb, 'nim-chat', 'x', '.', True, 0)
    assert guard.Ledger(str(tmp_path / 'ledger.db')).today()['nim-chat']['calls'] == 1


def test_run_and_claim_pause_before_side_effects(tmp_path, monkeypatch):
    pause = tmp_path / 'PAUSE'
    pause.write_text('hold')
    monkeypatch.setenv('BACKBONE_PAUSE_FILES', str(pause))
    cfg = {'db': str(tmp_path / 'router.db')}
    bb = Backbone.__new__(Backbone)
    bb.cfg = cfg
    with pytest.raises(guard.Blocked, match='paused'):
        bb.run('@host:any ignored')
    jobs = Jobs.__new__(Jobs)
    jobs.bb = bb
    # No con attribute: a paused claim must return before any database read or mutation.
    assert jobs._claim() is None
    assert jobs.claim_for_node('test') is None


def test_unattended_generic_workers_and_notifications_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKBONE_UNATTENDED', '1')
    monkeypatch.setenv('BACKBONE_PAUSE_FILES', '')
    from backbone import notify
    monkeypatch.setattr(notify, '_cred', lambda *a: pytest.fail('credentials accessed'))
    assert notify.notify('never send') is False
    bb = SimpleNamespace(cfg={})
    monkeypatch.setattr(Backbone, '_dispatch_raw', lambda *a: pytest.fail('worker ran'))
    assert not Backbone._dispatch(bb, 'pi', 'x', '.', False, 0).ok
    jobs = Jobs.__new__(Jobs)
    jobs.bb = bb
    assert jobs._claim() is None


def test_claim_budget_zero_leaves_pending(tmp_path, monkeypatch):
    monkeypatch.setenv('BACKBONE_PAUSE_FILES', '')
    monkeypatch.setenv('BACKBONE_BUDGET_CALLS', '0')
    jobs = Jobs.__new__(Jobs)
    jobs.bb = SimpleNamespace(cfg={})
    assert jobs._claim() is None and jobs.claim_for_node('test') is None


def test_credential_env_cannot_hide_global_pause(tmp_path, monkeypatch):
    pause = tmp_path / 'PAUSE'
    pause.write_text('hold')
    monkeypatch.setenv('BACKBONE_PAUSE_FILES', str(pause))
    with pytest.raises(guard.Blocked, match='paused'):
        guard.check('nim-chat', True, env={'NIM_1': 'fake-test-value'})


def test_subcent_usd_cap_not_rounded_away(tmp_path):
    ledger = guard.Ledger(str(tmp_path / 'ledger.db'))
    ledger.record('nim-chat', True, 0.00004)
    with pytest.raises(guard.Blocked, match='budget'):
        guard.check('nim-chat', True, env={'BACKBONE_PAUSE_FILES': '', 'BACKBONE_BUDGET_USD': '0.00003'}, ledger=ledger)


def test_interrupted_attempt_recovers_as_failure(queue, tmp_path):
    night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)
    path = queue.parent / 'dry-run/state.json'
    state = json.loads(path.read_text())
    state['tasks']['enrich-maps']['state'] = 'running'
    state['history'] = []
    path.write_text(json.dumps(state))
    result = night.tick(queue, dry_run=True, env=env(tmp_path), now=NOW)
    assert result['id'] == 'enrich-maps' and result['attempt'] == 2
    history = json.loads(path.read_text())['history']
    assert [r['state'] for r in history] == ['failed', 'done']


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS sandbox-exec required")
def test_enrich_mid_task_pause_kills_child(queue, tmp_path, monkeypatch):
    pause = tmp_path / 'PAUSE'
    calls = []
    class Child:
        pid = 12345
        def poll(self):
            return None
        def wait(self):
            calls.append('wait')
    def start(cmd, **kw):
        assert kw['start_new_session'] is True
        assert not any(k.startswith('NIM_') or 'TOKEN' in k for k in kw['env'])
        assert '--seeds' in cmd and '--out' in cmd and cmd[0] == '/usr/bin/sandbox-exec'
        pause.write_text('hold')
        return Child()
    monkeypatch.setattr(night.subprocess, 'Popen', start)
    monkeypatch.setattr(night.os, 'killpg', lambda *a: calls.append('kill'))
    monkeypatch.setattr(night, 'in_window', lambda *a, **k: True)
    task = night.load_queue(queue)[0]
    with pytest.raises(TimeoutError):
        night.enrich(task, queue, queue.parent / 'out/maps-enriched.csv', False, env(tmp_path))
    assert calls == ['kill', 'wait']


def test_child_watchdog_parent_pause_window_deadline(tmp_path, monkeypatch):
    from backbone import night_child
    monkeypatch.setattr(night_child.os, 'getppid', lambda: 123)
    pause = tmp_path / 'PAUSE'
    args = (123, [str(pause)], 23, 100, 200)
    assert night_child.should_stop(*args) is False
    assert night_child.should_stop(456, *args[1:]) is True
    assert night_child.should_stop(123, [str(pause)], 7, 100, 200) is True
    assert night_child.should_stop(123, [str(pause)], 23, 200, 200) is True
    pause.write_text('hold')
    assert night_child.should_stop(*args) is True
