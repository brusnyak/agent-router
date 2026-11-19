"""Bracket mode: idle-triggered daytime bounded work via the router.

Reuses night.py helpers (atomic, confined). Triggers when the Mac is idle
> 10 min, on AC power, PAUSE absent, load < 6, and no interactive Claude
on a TTY. Dispatches read-only tasks through Backbone.run so the router
picks the right worker and applies gates.

No sends, no spend, no third-party outreach. Only controller artifacts
(state/, out/) are writable.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from . import guard
from .night import atomic, confined

ROOT = Path.home() / 'Developer/agent-router'
TASKS = Path.home() / '.agent-router/data/bracket/tasks.yaml'
STATE_DIR = Path.home() / '.agent-router/data/bracket/state'
OUT_DIR = Path.home() / '.agent-router/data/bracket/out'
LOG = Path.home() / 'Library/Logs' / 'bracket-mode.log'
IDLE_SEC_DEFAULT = 600
TZ = ZoneInfo('Europe/Bratislava')


class TaskFailure(Exception):
    def __init__(self, rc):
        self.rc = rc


def idle_seconds() -> float | None:
    """Return seconds since last HID input, or None if unreadable."""
    try:
        out = subprocess.run(
            ['/usr/sbin/ioreg', '-c', 'IOHIDSystem'],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"IOHIDIdleTime" = ([0-9]+)', out)
    if not m:
        m = re.search(r'HIDIdleTime[^\n]*= ([0-9]+)', out)
    if not m:
        return None
    return int(m.group(1)) / 1e9


def ac_power() -> bool:
    try:
        out = subprocess.run(
            ['/usr/bin/pmset', '-g', 'batt'],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
        return 'AC Power' in out
    except (OSError, subprocess.SubprocessError):
        return False


def interactive_claude() -> bool:
    """True if a Claude process is attached to a real TTY (user is working)."""
    try:
        out = subprocess.run(
            ['/bin/ps', '-eo', 'tty=,command='],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return True  # fail closed
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        tty, command = parts
        if tty in ('??', ''):
            continue
        if re.search(r'(^|/)claude(\s|$)', command):
            return True
    return False


def load_ok() -> bool:
    try:
        return os.getloadavg()[0] < 6.0
    except OSError:
        return False


def paused() -> bool:
    for f in (Path.home() / '.agent-router/PAUSE',
              Path.home() / 'memory-vault/pages/dispatch-PAUSE'):
        if f.exists():
            return True
    return False


def log(event: dict) -> None:
    Path(LOG).parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + '\n')


def load_queue(path: Path):
    import yaml
    tasks = yaml.safe_load(path.read_text(encoding='utf-8-sig'))['tasks']
    ids = set()
    for task in tasks:
        if task['id'] in ids:
            raise ValueError(f'duplicate task id: {task["id"]}')
        if not task.get('prompt'):
            raise ValueError(f'task {task["id"]} missing prompt')
        if not task.get('gate'):
            raise ValueError(f'task {task["id"]} missing gate')
        if task['gate'] not in ('noop', 'pytest', 'compile'):
            raise ValueError(f'task {task["id"]} unsupported gate {task["gate"]}')
        ids.add(task['id'])
        confined(OUT_DIR, task['output'])
    return tasks


def load_state():
    p = STATE_DIR / 'state.json'
    if p.exists():
        return json.loads(p.read_text())
    return {'tasks': {}, 'history': []}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    atomic(STATE_DIR / 'state.json', json.dumps(state, indent=2))


def run_task(task, cwd=None):
    """Run one bracket task through the router with read_only + gate."""
    sys.path.insert(0, str(ROOT))
    from .core import Backbone  # noqa: E402

    bb = Backbone(env={'BACKBONE_UNATTENDED': '1',
                       'BACKBONE_NO_SECRETS_FILE': '1',
                       'PYTHONDONTWRITEBYTECODE': '1'})
    res = bb.run(
        task['prompt'],
        project='bracket',
        worker=task.get('worker', ''),
        gate=task.get('gate') or 'noop',
        read_only=True,
        cwd=cwd or str(ROOT),
    )
    return res


def tick(tasks_path=TASKS, *, force: bool = False, idle_sec: int = IDLE_SEC_DEFAULT) -> dict:
    now = dt.datetime.now(TZ)
    event = {'time': now.isoformat(), 'state': None, 'tasks_run': 0}

    if paused():
        event['state'] = 'halted'
        log(event)
        return event
    if not load_ok():
        event['state'] = 'load-high'
        log(event)
        return event
    if not ac_power():
        event['state'] = 'not-on-ac'
        log(event)
        return event
    if interactive_claude():
        event['state'] = 'interactive-claude'
        log(event)
        return event
    if not force:
        idle = idle_seconds()
        if idle is None:
            event['state'] = 'idle-unreadable'
            log(event)
            return event
        if idle < idle_sec:
            event['state'] = f'idle-{idle:.0f}s'
            log(event)
            return event

    path = Path(tasks_path).expanduser().resolve()
    tasks = load_queue(path)
    state = load_state()

    pending = [t for t in tasks
               if state['tasks'].get(t['id'], {}).get('state') != 'done']
    if not pending:
        event['state'] = 'complete'
        log(event)
        return event

    task = pending[0]
    record = state['tasks'].setdefault(task['id'], {'state': 'pending', 'attempts': 0})
    if record['attempts'] >= 3:
        event['state'] = 'retry-exhausted'
        event['task'] = task['id']
        log(event)
        return event

    record.update(state='running', attempts=record['attempts'] + 1)
    save_state(state)

    event.update(id=task['id'], kind=task.get('kind', 'review'),
                 attempt=record['attempts'], state='running')
    try:
        res = run_task(task)
        ok = bool(res.get('output')) and res.get('state') != 'failed'
        event.update(state='done' if ok else 'failed', rc=0 if ok else 1,
                     output_preview=str(res.get('output', ''))[:200],
                     plan=res.get('plan', {}))
        record['state'] = 'done' if ok else 'failed'
    except Exception as exc:  # noqa: BLE001
        event.update(state='failed', rc=1, error=type(exc).__name__)
        record['state'] = 'failed'

    state['history'].append(event)
    save_state(state)
    log(event)
    return event


def run_tick(tasks_path=None, *, force: bool = False, idle_sec: int = IDLE_SEC_DEFAULT) -> int:
    result = tick(tasks_path or str(TASKS), force=force, idle_sec=idle_sec)
    print(json.dumps(result, ensure_ascii=False))
    return result['rc']


if __name__ == '__main__':  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--tasks', default=str(TASKS))
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--idle-sec', type=int, default=IDLE_SEC_DEFAULT)
    a = ap.parse_args()
    raise SystemExit(run_tick(a.tasks, force=a.force, idle_sec=a.idle_sec))
