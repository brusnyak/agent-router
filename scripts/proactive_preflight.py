#!/usr/bin/env python3
"""Read-only proactive eligibility snapshot; never enqueue, probe workers or load keys.

Run with the same BACKBONE_* environment as the scheduled service. Health is
cached evidence only, never proof a worker will succeed. Live state can change
after this snapshot; the executor must still enforce every guard.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def read_db(path):
    """Missing DB is an error, never silently create an empty production DB."""
    con = sqlite3.connect(Path(path).expanduser().resolve().as_uri() + '?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con


def inspect(manifest_path, cfg, *, env=None, now=None, load=None, doctor_path=None):
    from backbone import guard
    from backbone.proactive import _day
    now = time.time() if now is None else now
    env = dict(os.environ) if env is None else env
    base = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(base.read_text())
    # Same host-local calendar boundary as scheduler reservations, not UTC
    # assumed from the coordinator's usual deployment timezone.
    day = _day(now)
    with read_db(cfg['db']) as con:
        rows = {r['goal_id']: dict(r) for r in con.execute('SELECT * FROM proactive_goals')}
        nodes = {r['name']: dict(r) for r in con.execute('SELECT * FROM nodes')}
    goals = manifest['goals']
    used = sum(rows.get(g['id'], {}).get('day_count', 0) for g in goals
               if rows.get(g['id'], {}).get('day') == day)
    active = sum(bool(rows.get(g['id'], {}).get('active_job')) for g in goals)
    pause = guard.paused(cfg, env)
    ledger = None
    ledger_con = None
    lp = guard.ledger_path(cfg)
    if lp and Path(lp).exists():
        ledger_con = read_db(lp)
        def today(_now=None):
            return {r[0]: {'calls': r[1], 'usd': r[2]} for r in ledger_con.execute(
                'SELECT worker,count(*),coalesce(sum(cost),0) FROM calls WHERE day=? GROUP BY worker', (day,))}
        ledger = SimpleNamespace(con=ledger_con, today=today, day=lambda _: day)
    health = {}
    if doctor_path:
        try:
            doctor = json.loads(Path(doctor_path).expanduser().read_text())
            if 0 <= now - float(doctor['saved_at']) <= 21600:
                health = {a['name']: a.get('usable') for a in doctor.get('agents', [])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    results = []
    try:
        for g in sorted(goals, key=lambda g: (g['priority'], g['id'])):
            r = rows.get(g['id'], {})
            missing = [p for p in g['source_paths'] if not (base.parent / os.path.expanduser(p)).exists()]
            target = nodes.get(g.get('target'))
            reason = ''
            if pause: reason = 'paused'
            elif load is not None and load >= manifest.get('max_load', float('inf')): reason = 'host load'
            elif active >= manifest.get('max_active', 1): reason = 'max active'
            elif used >= manifest.get('daily_limit', 12): reason = 'global daily limit'
            elif not g['enabled']: reason = 'disabled'
            elif r.get('active_job'): reason = 'already active'
            elif missing: reason = 'missing source'
            elif g.get('target') and (not target or now - target['last_seen'] >= 60): reason = 'target offline'
            elif g.get('requires_idle') and json.loads(target['caps']).get('idle_state') != 'ready': reason = 'target active or idle unavailable'
            elif r.get('next_due', 0) > now: reason = 'cooldown'
            elif r.get('day') == day and r.get('day_count', 0) >= g.get('daily_limit', 4): reason = 'goal daily limit'
            worker = g['worker'].partition(':')[0]
            dispatch = ''
            try:
                guard.check(worker, g.get('read_only', True), cfg, env, ledger=ledger, now=now)
            except guard.Blocked as e:
                dispatch = str(e)
            results.append({'goal': g['id'], 'scheduler': reason or 'eligible',
                            'dispatch_guard': dispatch or 'passes', 'missing_sources': missing,
                            'worker_health': {True: 'cached usable', False: 'cached unusable'}.get(health.get(worker), 'unknown'),
                            'seq': r.get('seq', 0), 'day_count': r.get('day_count', 0),
                            'next_due': r.get('next_due', 0), 'failures': r.get('failures', 0)})
    finally:
        if ledger_con: ledger_con.close()
    return {'snapshot_only': True, 'day': day, 'global_used': used,
            'global_limit': manifest.get('daily_limit', 12), 'pause_file': pause, 'goals': results}


def main():
    from backbone.core import load_config, ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default='~/memory-vault/pages/plans/proactive-goals.json')
    parser.add_argument('--config')
    args = parser.parse_args()
    try:
        result = inspect(args.manifest, load_config(args.config), load=os.getloadavg()[0],
                         doctor_path=Path(ROOT) / 'data/doctor.json')
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
        print(json.dumps({'error': type(e).__name__, 'snapshot_only': True}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
