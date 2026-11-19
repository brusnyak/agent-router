"""One bounded research task per tick. No workers, models, MCP, shell or send tools.
Dry runs simulate 23:00, use fixtures and separate state/output; PAUSE still applies.
"""
from __future__ import annotations
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo
from . import guard

TZ = ZoneInfo('Europe/Bratislava')
DEFAULT_TASKS = '~/Developer/founder-runs/night/tasks.yaml'


class TaskFailure(Exception):
    def __init__(self, rc):
        self.rc = rc


def in_window(start=23, end=7, now=None):
    hour = (now or dt.datetime.now(TZ)).astimezone(TZ).hour
    return start <= hour < end if start < end else hour >= start or hour < end


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a leftover .tmp symlink redirecting writes.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                     dir=path.parent, prefix='.' + path.name + '.',
                                     delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def confined(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('output escapes directory')
    return path


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'name', 'site', 'status', 'sources'} <= set(reader.fieldnames or ()):
            raise ValueError('CSV schema gate')
        data = list(reader)
    if not data or any(r['status'] not in ('READY', 'NEEDS_X', 'DROP') for r in data):
        raise ValueError('CSV status/count gate')
    for row in data:
        if not isinstance(json.loads(row['sources']), dict):
            raise ValueError('provenance gate')
        if row['status'] == 'READY' and not json.loads(row['sources']):
            raise ValueError('READY provenance gate')
    return data


def load_queue(path):
    import yaml
    tasks = yaml.safe_load(path.read_text())['tasks']
    ids = set()
    gates = {'enrich': 'csv-provenance', 'summary': 'counts-match',
             'drafts': 'facts-only-top5', 'morning': 'history-match'}
    for task in tasks:
        if task['id'] in ids or task['kind'] not in gates:
            raise ValueError('duplicate ID/unsupported kind')
        if task['acceptance'] != gates[task['kind']]:
            raise ValueError('unsupported gate')
        if task['kind'] == 'morning' and task['output'] != 'morning.md':
            raise ValueError('morning output must be morning.md')
        if task['kind'] in ('summary', 'drafts') and not task.get('inputs'):
            raise ValueError('missing CSV inputs')
        if not set(task.get('requires', [])) <= ids:
            raise ValueError('dependencies must precede task')
        ids.add(task['id'])
        confined(path.parent / 'out', task['output'])
        for value in task.get('inputs', []):
            confined(path.parent / 'out', value)
        if task['kind'] == 'enrich' and task['seeds'] not in (
                '../leads/out/maps-seed-sk.csv', '../research/2026-11-18-realtor-seeds.csv'):
            raise ValueError('unapproved seeds')
    return tasks


def enrich(task, queue, output, dry, env):
    if dry:
        atomic(output, 'name,site,status,sources\nFixture,https://example.invalid,NEEDS_X,{}\n')
    else:
        script = queue.parent.parent / 'leads/leadgen.py'
        # Fail closed without the macOS write sandbox. Public-page GETs only in leadgen.py.
        sandbox = Path('/usr/bin/sandbox-exec')
        if not sandbox.exists():
            raise ValueError('OS sandbox unavailable')
        policy = '(version 1)(allow default)(deny file-write*)(allow file-write* (subpath ' + json.dumps(str(output.parent)) + '))'
        cmd = [str(sandbox), '-p', policy, sys.executable, '-B',
               str(Path(__file__).with_name('night_child.py')), str(os.getpid()), str(script),
               '--seeds', str((queue.parent / task['seeds']).resolve()), '--out', str(output)]
        child_env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                     'PYTHONDONTWRITEBYTECODE': '1', 'BACKBONE_UNATTENDED': '1',
                     'BACKBONE_PAUSE_FILES': ':'.join(guard.pause_files(env=env))}
        proc = subprocess.Popen(cmd, env=child_env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.monotonic() + min(int(task.get('timeout_s', 600)), 600)
        try:
            while proc.poll() is None:
                if guard.paused(env=env) or not in_window() or time.monotonic() >= deadline:
                    raise TimeoutError('paused or timeout')
                time.sleep(0.1)
            if proc.returncode:
                raise TaskFailure(proc.returncode)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
    data = rows(output)
    if not dry:
        with (queue.parent / task['seeds']).open(encoding='utf-8-sig', newline='') as stream:
            if len(data) != len(list(csv.DictReader(stream))):
                raise ValueError('seed/output count gate')
    return {s: sum(r['status'] == s for r in data) for s in ('READY', 'NEEDS_X', 'DROP')}


def execute(task, queue, out, dry, env):
    output = confined(out, task['output'])
    output.parent.mkdir(parents=True, exist_ok=True)
    if task['kind'] == 'enrich':
        return enrich(task, queue, output, dry, env)
    if task['kind'] == 'morning':
        return {}  # controller writes history after recording the outcome
    datasets = {name: rows(confined(out, name)) for name in task['inputs']}
    counts = {name: {s: sum(r['status'] == s for r in data) for s in ('READY', 'NEEDS_X', 'DROP')}
              for name, data in datasets.items()}
    if task['kind'] == 'summary':
        atomic(output, json.dumps(counts, indent=2) + '\n')
        if json.loads(output.read_text()) != counts:
            raise ValueError('counts gate')
    else:
        drafts = []
        for name, data in datasets.items():
            for index, row in enumerate([r for r in data if r['status'] == 'READY'][:5], 1):
                sources = json.loads(row['sources'])
                if not row['name'] or not row['site'] or not sources.get('site'):
                    raise ValueError('draft fact provenance gate')
                content = ('DRAFT — OWNER REVIEW REQUIRED — DO NOT SEND\n'
                           f"CSV: {name}; READY row: {index}\n"
                           f"Dobrý deň, píšem vám ohľadom webu {row['site']} ({row['name']}). "
                           'Na koho sa môžem obrátiť s konkrétnym návrhom k tomuto webu?\n'
                           f"Evidence: {json.dumps(sources['site'], ensure_ascii=False)}\n")
                draft = output.parent / f'{output.stem}-{Path(name).stem}-{index}.txt'
                atomic(draft, content)
                if draft.read_text() != content:
                    raise ValueError('draft gate')
                drafts.append(str(draft))
        atomic(output, json.dumps({'drafts': drafts, 'counts': counts}, indent=2) + '\n')
    return counts


def morning(out, state):
    lines = ['# Night run — local artifacts only', '', f"Night: {state['night']}",
             f"Consecutive failures: {state['consecutive_failures']}",
             'Live verification: unverified until enrichment gates pass.', '']
    for event in state['history']:
        lines.append(f"- {event['id']}: {event['state']} rc={event['rc']} task_rc={event.get('task_rc', event['rc'])} attempt={event['attempt']} counts={json.dumps(event.get('counts', {}))} error={event.get('error', '')}")
    content = '\n'.join(lines) + '\n'
    atomic(out / 'morning.md', content)
    if (out / 'morning.md').read_text() != content:
        raise ValueError('history gate')


def tick(tasks_path=DEFAULT_TASKS, *, dry_run=False, env=None, now=None):
    env = os.environ if env is None else env
    if guard.paused(env=env):
        return {'state': 'halted', 'rc': 0, 'tasks_run': 0}
    now = now or dt.datetime.now(TZ)
    if not dry_run and not in_window(now=now):
        return {'state': 'out-of-window', 'rc': 0, 'tasks_run': 0}
    queue = Path(tasks_path).expanduser().resolve()
    tasks = load_queue(queue)
    root = queue.parent / ('dry-run' if dry_run else '')
    out = root / 'out'
    if not out.resolve().is_relative_to(queue.parent):
        raise ValueError('output directory escapes queue')
    out.mkdir(parents=True, exist_ok=True)
    state_path = root / 'state.json'
    with (root / 'tick.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'busy', 'rc': 0, 'tasks_run': 0}
        digest = hashlib.sha256(queue.read_bytes()).hexdigest()
        night = (now.astimezone(TZ) - dt.timedelta(hours=7)).date().isoformat()
        state = json.loads(state_path.read_text()) if state_path.exists() else {
            'queue_sha256': digest, 'night': night, 'consecutive_failures': 0, 'tasks': {}, 'history': []}
        if state['queue_sha256'] != digest:
            raise ValueError('queue changed; archive reviewed state before continuing')
        if state['night'] != night:
            state.update(night=night, consecutive_failures=0)
        for id_, record in state['tasks'].items():
            if record['state'] == 'running':
                record['state'] = 'failed'
                state['consecutive_failures'] += 1
                state['history'].append({'id': id_, 'state': 'failed', 'rc': 1,
                                         'attempt': record['attempts'], 'error': 'interrupted tick'})
        if state['consecutive_failures'] >= 2:
            atomic(state_path, json.dumps(state, indent=2))
            morning(out, state)
            return {'state': 'stopped-for-night', 'rc': 1, 'tasks_run': 0}
        task = next((t for t in tasks if state['tasks'].get(t['id'], {}).get('state') != 'done'), None)
        if task is None:
            return {'state': 'complete', 'rc': 0, 'tasks_run': 0}
        record = state['tasks'].setdefault(task['id'], {'state': 'pending', 'attempts': 0})
        if record['attempts'] >= 3:
            return {'state': 'retry-exhausted', 'rc': 1, 'tasks_run': 0}
        if guard.paused(env=env):
            return {'state': 'halted', 'rc': 0, 'tasks_run': 0}
        record.update(state='running', attempts=record['attempts'] + 1)
        atomic(state_path, json.dumps(state, indent=2))
        event = {'id': task['id'], 'operation': task['kind'], 'output': task['output'],
                 'time': now.isoformat(), 'attempt': record['attempts'], 'state': 'done', 'rc': 0, 'task_rc': 0}
        try:
            if any(state['tasks'].get(dep, {}).get('state') != 'done' for dep in task.get('requires', [])):
                raise ValueError('dependency gate')
            event['counts'] = execute(task, queue, out, dry_run, env)
        except Exception as exc:
            # Do not serialize arbitrary errors; they can contain credentials or HTTP bodies.
            event.update(state='failed', rc=1, task_rc=exc.rc if isinstance(exc, TaskFailure) else 1,
                         error=type(exc).__name__)
        record['state'] = event['state']
        state['consecutive_failures'] = state['consecutive_failures'] + 1 if event['rc'] else 0
        state['history'].append(event)
        atomic(state_path, json.dumps(state, indent=2))
        morning(out, state)
        return {**event, 'tasks_run': 1, 'dry_run': dry_run, 'state_path': str(state_path)}


def run_tick(cfg_path=None, prompt='', *, tasks_path=None, dry_run=False):
    try:
        result = tick(tasks_path or cfg_path or DEFAULT_TASKS, dry_run=dry_run)
    except Exception as exc:
        result = {'state': 'blocked', 'rc': 1, 'error': type(exc).__name__, 'tasks_run': 0}
    print(json.dumps(result))
    return result['rc']


def run_loop(cfg_path=None, prompt=''):
    # Compatibility: legacy --loop callers get exactly one bounded tick.
    return run_tick(cfg_path, prompt)
