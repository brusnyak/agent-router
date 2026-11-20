"""Offline factory feed acceptance gate; all sources live in temporary directories."""
import contextlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backbone.factory_status import collect


class FactoryStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1800000000
        self.config = self.root / 'factory.json'
        self.env = patch.dict(os.environ, {'AGENT_ROUTER_HOME': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def feed(self):
        return collect(now=self.now)

    def db(self, runs=(), jobs=()):
        path = self.root / 'data/backbone.db'
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(path)) as con:
            con.executescript('''
                CREATE TABLE runs(id TEXT, worker TEXT, state TEXT, created REAL, updated REAL);
                CREATE TABLE jobs(id TEXT, state TEXT, run_id TEXT, created REAL, updated REAL);
                CREATE TABLE steps(id INTEGER PRIMARY KEY, run_id TEXT, kind TEXT, ok INTEGER);
            ''')
            con.executemany('INSERT INTO runs VALUES(?,?,?,?,?)', runs)
            con.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)', jobs)
            con.commit()
        return path

    def test_missing_sources_are_unknown_and_create_nothing(self):
        result = self.feed()
        self.assertEqual(result['router']['running'], 'unknown')
        self.assertEqual(result['router']['last_runs'], 'unknown')
        self.assertEqual(result['nodes']['mac']['load'], 'unknown')
        self.assertEqual(result['limits'], 'unknown')
        self.assertEqual(result['career_agent']['prepared_today'], 'unknown')
        self.assertEqual(result['upwork_scan']['counts_by_grade'], 'unknown')
        self.assertEqual(result['inbox_monitor']['events'], 'unknown')
        self.assertEqual(result['outreach_queue']['pending_approvals'], 'unknown')
        self.assertEqual(result['stalled'], 'unknown')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_known_sources_can_report_zero(self):
        self.db()
        (self.root / 'backlog.jsonl').write_text('')
        result = self.feed()
        self.assertEqual(result['router']['running'], 0)
        self.assertEqual(result['router']['queued'], 0)
        self.assertEqual(result['router']['last_runs'], [])
        self.assertIs(result['stalled'], False)

    def test_router_deduplicates_linked_jobs_and_limits_history(self):
        runs = [(str(i), 'worker', 'done', self.now-i, self.now-i) for i in range(15)]
        runs[0] = ('0', 'worker', 'running', self.now-1000, self.now)
        path = self.db(runs, [('a', 'running', '0', self.now-1000, self.now),
                              ('b', 'pending', '', self.now-900, self.now)])
        with contextlib.closing(sqlite3.connect(path)) as con:
            con.executemany('INSERT INTO steps(run_id,kind,ok) VALUES(?,?,?)',
                            [('1', 'gate', 0), ('1', 'gate', 1), ('2', 'gate', 0), ('3', 'work', 1)])
            con.commit()
        result = self.feed()['router']
        self.assertEqual((result['running'], result['queued']), (1, 1))
        self.assertEqual(len(result['last_runs']), 10)
        self.assertEqual(result['last_runs'][0]['worker'], 'worker')
        self.assertEqual(result['last_runs'][0]['gate'], 'pass')
        self.assertEqual(result['last_runs'][1]['gate'], 'fail')
        self.assertEqual(result['last_runs'][2]['gate'], 'unknown')
        self.assertEqual(result['last_runs'][0]['age_s'], 1)

    def test_stalled_ignores_running_heartbeats(self):
        self.db([('r', 'worker', 'running', self.now-900, self.now)],
                [('q', 'pending', '', self.now-1000, self.now)])
        self.assertIs(self.feed()['stalled'], True)

    def test_recent_finish_clears_stall(self):
        self.db([('r', 'worker', 'done', self.now-900, self.now-1)],
                [('q', 'pending', '', self.now-1000, self.now-1000)])
        self.assertIs(self.feed()['stalled'], False)

    def test_never_started_queue_ages_from_enqueue(self):
        self.db(jobs=[('q', 'pending', '', self.now-600, self.now)])
        self.assertIs(self.feed()['stalled'], True)

    def test_recent_start_clears_stall(self):
        self.db([('r', 'worker', 'running', self.now-1, self.now)])
        self.assertIs(self.feed()['stalled'], False)

    def test_backlog_only_uses_observed_age(self):
        self.db()
        path = self.root / 'backlog.jsonl'
        path.write_text('{"prompt":"task"}\n')
        os.utime(path, (self.now-700, self.now-700))
        self.assertIs(self.feed()['stalled'], True)

    def test_missing_router_never_proves_stall(self):
        (self.root / 'backlog.jsonl').write_text('{"prompt":"task"}\n')
        self.assertEqual(self.feed()['stalled'], 'unknown')

    def test_nodes_independent_of_router_and_missing_load(self):
        self.write('monitor/mac.json', {'ts': self.now-1, 'load1': 3.2})
        self.write('monitor/oracle.json', {'ts': self.now-901})
        nodes = self.feed()['nodes']
        self.assertEqual(nodes['mac']['freshness'], 'fresh')
        self.assertEqual(nodes['mac']['load'], 3.2)
        self.assertEqual(nodes['oracle']['freshness'], 'stale')
        self.assertEqual(nodes['oracle']['load'], 'unknown')

    def test_idle_latest_complete_record_with_timestamp(self):
        (self.root / 'idle-tick.log').write_text(
            '2026-11-20T10:00:00+00:00 {"state":"active"}\n'
            '{"ts": 1800000000, "state":"paused"}\n{"state":')
        self.assertEqual(self.feed()['idle_tick'], {'last_tick': self.now, 'state': 'paused'})

    def test_idle_pretty_json_does_not_invent_time(self):
        (self.root / 'idle-tick.log').write_text(json.dumps({'state': 'empty'}, indent=2))
        self.assertEqual(self.feed()['idle_tick'], {'last_tick': 'unknown', 'state': 'empty'})

    def test_idle_nested_item_state_does_not_override_tick(self):
        self.write('idle-tick.log', {'ts': self.now, 'state': 'submitted', 'item': {'state': 'queued'}})
        self.assertEqual(self.feed()['idle_tick']['state'], 'submitted')

    def test_invalid_types_and_extreme_times_do_not_crash(self):
        self.write('factory.json', {'idle_threshold_s': [], 'node_fresh_s': 'bad',
                                   'inbox_monitor': 'inbox.json', 'career_runs': 'receipts'})
        self.write('limits.json', {'idle_minutes': 'bad'})
        self.write('inbox.json', {'last_run': 1e300, 'events': -1})
        self.write('receipts/a.json', {'completed_at': 1e300})
        self.write('monitor/mac.json', {'ts': 1e300, 'load1': False})
        self.assertEqual(self.feed()['inbox_monitor'], {'last_run': 'unknown', 'events': 'unknown'})
        self.assertEqual(self.feed()['nodes']['mac']['freshness'], 'unknown')

    def test_permission_failure_is_unknown(self):
        with patch.object(Path, 'read_text', side_effect=PermissionError):
            self.assertEqual(self.feed()['idle_tick']['last_tick'], 'unknown')

    def test_configured_sources_and_relative_paths(self):
        self.write('factory.json', {'career_runs': 'receipts', 'career_db': 'career.db',
                                   'career_digest_dir': 'digest', 'inbox_monitor': 'inbox.json',
                                   'upwork_index': 'INDEX.md', 'idle_threshold_s': 42})
        for i in (1, 2):
            self.write(f'receipts/{i}.json', {'completed_at': self.now-i, 'prepared': [{'id': 'a', 'version': i}]})
        self.write('receipts/old.json', {'completed_at': self.now-86400, 'prepared': [{'id': 'old'}]})
        self.write('digest/2026-11-20-batch.md', 'digest')
        with contextlib.closing(sqlite3.connect(self.root / 'career.db')) as con:
            con.execute('CREATE TABLE applications(submitted_at REAL)')
            con.executemany('INSERT INTO applications VALUES(?)', [(self.now,), (None,), (self.now-86400,)])
            con.commit()
        self.write('inbox.json', {'last_run': self.now-2, 'events': []})
        (self.root / 'INDEX.md').write_text('- 2026-11-19 10:00 seen 1\n  - [A] old\n'
                                           '- 2026-11-20 10:00 seen 2\n  - [B] one\n  - [D] two\n')
        result = self.feed()
        self.assertEqual(result['career_agent']['last_daily_run'], self.now-1)
        self.assertEqual(result['career_agent']['prepared_today'], 1)
        self.assertEqual(result['career_agent']['applied_today'], 1)
        self.assertTrue(result['career_agent']['last_digest_path'].endswith('-batch.md'))
        self.assertEqual(result['inbox_monitor']['events'], [])
        self.assertEqual(result['upwork_scan']['counts_by_grade'], {'A': 0, 'B': 1, 'C': 0, 'D': 1})
        self.assertEqual(result['idle_threshold_s'], 42)

    def test_outreach_excludes_other_kinds_and_approved(self):
        path = self.root / 'data/approvals.db'
        path.parent.mkdir()
        with contextlib.closing(sqlite3.connect(path)) as con:
            con.execute('CREATE TABLE cards(kind TEXT, decision TEXT)')
            con.executemany('INSERT INTO cards VALUES(?,?)', [('outreach', 'pending'), ('outreach', 'later'),
                                                                          ('outreach', 'approve'), ('application', 'pending')])
            con.commit()
        self.assertEqual(self.feed()['outreach_queue']['pending_approvals'], 2)

    def test_corrupt_sources_remain_unknown(self):
        self.config.write_text('[]')
        (self.root / 'limits.json').write_text('bad')
        self.write('monitor/mac.json', {'ts': 'bad', 'load1': None})
        self.write('monitor/oracle.json', [])
        (self.root / 'backlog.jsonl').write_text('bad\n')
        (self.root / 'data').mkdir()
        (self.root / 'data/backbone.db').write_text('bad')
        result = self.feed()
        self.assertEqual(result['router']['running'], 'unknown')
        self.assertEqual(result['backlog'], 'unknown')
        self.assertEqual(result['limits'], 'unknown')
        self.assertEqual(result['nodes']['mac']['load'], 'unknown')

    def test_limits_override_and_no_source_mutation(self):
        self.write('limits.json', {'idle_minutes': 1, 'max_workers': 4})
        self.db(jobs=[('q', 'pending', '', self.now-61, self.now)])
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertIs(self.feed()['stalled'], True)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_cli_one_json_document_without_optional_packages(self):
        proc = subprocess.run([sys.executable, '-S', '-m', 'backbone', 'factory-status', '--json',
                               '--config', str(self.config)], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['stalled'], 'unknown')
        self.assertEqual(proc.stderr, '')


if __name__ == '__main__':
    unittest.main()
