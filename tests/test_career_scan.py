import json
import subprocess
from pathlib import Path
from backbone import career_scan, idle_policy


def _posting(i, text, **extra):
    return {'ok': True, 'title': f'Role {i}', 'url': f'https://example.test/job/{i}',
            'observed_at': '2026-11-19T10:00:00Z', 'skills': ['python'], 'text': text, **extra}


def _stdout(rows, seen=None, passed=None):
    return json.dumps({'seen': len(rows) if seen is None else seen,
                       'passed': len(rows) if passed is None else passed, 'postings': rows}, ensure_ascii=False)


def _run_with(monkeypatch, stdout, returncode=0, stderr='1 pass', **kwargs):
    monkeypatch.setattr(career_scan, 'available', lambda *a, **k: True)
    seen = {}
    def run(cmd, cwd, timeout, env):
        seen.update(cmd=cmd, cwd=cwd, timeout=timeout, env=env)
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)
    monkeypatch.setattr(career_scan, 'run_group', run)
    return career_scan.run(**kwargs), seen


def test_fixed_collector_is_sandboxed_and_does_not_inherit_keys(monkeypatch):
    monkeypatch.setenv('NIM_5', 'fake-test-secret')
    result, seen = _run_with(monkeypatch, _stdout([_posting(1, 'qualified text')]))
    assert result.ok and 'qualified text' in result.text
    assert seen['cmd'][0] == '/usr/bin/sandbox-exec'
    assert '(deny file-write*)' in seen['cmd'][2]
    assert seen['timeout'] == 120 and 'NIM_5' not in seen['env']
    assert 'CAREER_PROFILE_PATH' not in seen['env']
    assert seen['cwd'] == str(career_scan.ROOT)


def test_valid_data_preserved_structured(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'short body')]), stderr='1 pass')
    evidence = json.loads(result.text)
    assert result.ok and evidence['status'] == 'ok'
    assert evidence['seen'] == 1 and evidence['passed'] == 1 and evidence['omitted_postings'] == 0
    post = evidence['postings'][0]
    assert post['title'] == 'Role 1' and post['url'] == 'https://example.test/job/1'
    assert post['observed_at'] == '2026-11-19T10:00:00Z' and post['skills'] == ['python']
    assert post['text'] == 'short body' and post['description_truncated'] is False
    assert post['full_description_required'] is True
    assert evidence['qualification_counts'] == '1 pass'


def test_malformed_output_blocked_on_zero_exit(monkeypatch):
    result, _ = _run_with(monkeypatch, 'Traceback: not json')
    assert not result.ok and json.loads(result.text)['status'] == 'blocked'


def test_nonobject_payload_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, '[1, 2, 3]')
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'


def test_schema_invalid_payload_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, json.dumps({'seen': 'x', 'passed': 0, 'postings': []}))
    assert not result.ok
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'a')], seen=2))
    assert not result.ok
    result, _ = _run_with(monkeypatch, json.dumps({'seen': 1, 'passed': 1, 'postings': ['not-a-dict']}))
    assert not result.ok


def test_negative_counts_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'a')], passed=-1))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'


def test_passed_greater_than_seen_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'a')], passed=2))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'


def test_passed_must_equal_ok_row_count(monkeypatch):
    rows = [_posting(1, 'a'), _posting(2, 'b', ok=False)]
    result, _ = _run_with(monkeypatch, _stdout(rows, passed=2))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'
    result, _ = _run_with(monkeypatch, _stdout(rows, passed=1))
    assert result.ok and json.loads(result.text)['passed'] == 1


def test_seen_above_eight_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(i, 'a') for i in range(9)]))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'


def test_title_and_url_must_be_strings(monkeypatch):
    bad_title = _posting(1, 'a', title=None)
    result, _ = _run_with(monkeypatch, _stdout([bad_title]))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'
    bad_url = _posting(1, 'a', url=['https://example.test'])
    result, _ = _run_with(monkeypatch, _stdout([bad_url]))
    assert not result.ok and json.loads(result.text)['reason'] == 'collector output invalid'


def test_passed_rows_selected_before_rejected(monkeypatch):
    rows = [_posting(0, 'r0', ok=False), _posting(1, 'r1', ok=False), _posting(2, 'r2', ok=False),
            _posting(3, 'p3'), _posting(4, 'p4')]
    result, _ = _run_with(monkeypatch, _stdout(rows, passed=2))
    evidence = json.loads(result.text)
    assert [p['title'] for p in evidence['postings']] == ['Role 3', 'Role 4', 'Role 0']
    assert [p['ok'] for p in evidence['postings']] == [True, True, False]
    assert evidence['seen'] == 5 and evidence['passed'] == 2 and evidence['omitted_postings'] == 2


def test_zero_rows_blocked_as_no_observed_postings(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([]))
    evidence = json.loads(result.text)
    assert not result.ok and evidence['status'] == 'blocked'
    assert evidence['reason'] == 'no observed postings'


def test_flat_fields_only_nested_payloads_dropped(monkeypatch):
    row = _posting(1, 'body', why='matched', source='djinni', payload={'deep': {'x': [1, 2]}},
                   skills=['python', {'nested': 'dict'}, 'x' * 100] + [f's{i}' for i in range(30)])
    result, _ = _run_with(monkeypatch, _stdout([row]))
    post = json.loads(result.text)['postings'][0]
    assert 'payload' not in post
    assert post['why'] == 'matched' and post['source'] == 'djinni' and post['ok'] is True
    assert all(isinstance(s, str) and len(s) <= career_scan.SKILL_CAP for s in post['skills'])
    # first 20 slots: 'python', dict (dropped), 100-char string (capped), s0..s16 -> 19 strings
    assert len(post['skills']) == 19 and post['skills'][1] == 'x' * career_scan.SKILL_CAP
    assert post['fields_truncated'] is True


def test_long_string_field_capped_and_flagged(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'a', title='T' * 1000)]))
    post = json.loads(result.text)['postings'][0]
    assert len(post['title']) == career_scan.FIELD_CAP and post['fields_truncated'] is True


def test_nonzero_exit_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, _stdout([_posting(1, 'a')]), returncode=3)
    assert not result.ok and json.loads(result.text)['exit_code'] == 3


def test_oversize_stdout_blocked(monkeypatch):
    result, _ = _run_with(monkeypatch, '{' + ' ' * (career_scan.MAX_STDOUT + 1) + '}')
    assert not result.ok and json.loads(result.text)['status'] == 'blocked'


def test_multibyte_large_eight_postings_bounded(monkeypatch):
    body = 'Досвід роботи з Python 🚀 ' * 260  # multibyte, > 6000 chars per row
    rows = [_posting(i, body[:6000]) for i in range(8)]
    result, _ = _run_with(monkeypatch, _stdout(rows))
    assert result.ok
    assert len(result.text) <= career_scan.MAX_RESULT
    evidence = json.loads(result.text)
    assert evidence['seen'] == 8 and evidence['passed'] == 8
    assert len(evidence['postings']) == career_scan.MAX_POSTINGS
    assert evidence['omitted_postings'] == 5
    for i, post in enumerate(evidence['postings']):
        assert post['title'] == f'Role {i}' and post['url'] == f'https://example.test/job/{i}'
        assert post['description_truncated'] is True
        assert post['full_description_required'] is True
        assert len(post['text']) < 6000


def test_configured_root_and_profile_used_without_key_leak(monkeypatch, tmp_path):
    root = tmp_path / 'career-agent'
    (root / '.venv/bin').mkdir(parents=True)
    (root / '.venv/bin/python').write_text('')
    profile = tmp_path / 'private' / 'profile.yaml'
    monkeypatch.setenv('NIM_5', 'fake-test-secret')
    result, seen = _run_with(monkeypatch, _stdout([_posting(1, 'ok')]),
                             root=str(root), profile_path=str(profile))
    assert result.ok
    assert seen['cmd'][3] == str(root / '.venv/bin/python')
    assert seen['cwd'] == str(root)
    assert seen['env']['PYTHONPATH'] == str(root / 'src')
    assert seen['env']['CAREER_PROFILE_PATH'] == str(profile)
    assert 'NIM_5' not in seen['env'] and 'fake-test-secret' not in json.dumps(seen['env'])
    assert 'load_profile(Path(pp))' in seen['cmd'][-1]


def test_configured_root_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    (tmp_path / 'ca/.venv/bin').mkdir(parents=True)
    (tmp_path / 'ca/.venv/bin/python').write_text('')
    result, seen = _run_with(monkeypatch, _stdout([_posting(1, 'ok')]), root='~/ca', profile_path='~/p.yaml')
    assert result.ok
    assert seen['cwd'] == str(tmp_path / 'ca')
    assert seen['env']['CAREER_PROFILE_PATH'] == str(tmp_path / 'p.yaml')


def test_idle_collector_refuses_active_mac(monkeypatch):
    monkeypatch.setattr(career_scan, 'available', lambda *a, **k: True)
    monkeypatch.setattr(idle_policy, 'current_snapshot', lambda: idle_policy.Snapshot(0, True, 0, False))
    monkeypatch.setattr(career_scan, 'run_group', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not execute')))
    assert not career_scan.run(idle=True).ok
