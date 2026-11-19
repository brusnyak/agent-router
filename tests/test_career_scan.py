import subprocess
from backbone import career_scan, idle_policy


def test_fixed_collector_is_sandboxed_and_does_not_inherit_keys(monkeypatch):
    monkeypatch.setattr(career_scan, 'available', lambda: True)
    monkeypatch.setenv('NIM_5', 'fake-test-secret')
    seen = {}
    def run(cmd, cwd, timeout, env):
        seen.update(cmd=cmd, timeout=timeout, env=env)
        return subprocess.CompletedProcess(cmd, 0, 'qualified listing', '1 pass')
    monkeypatch.setattr(career_scan, 'run_group', run)
    result=career_scan.run()
    assert result.ok and 'qualified listing' in result.text
    assert seen['cmd'][0] == '/usr/bin/sandbox-exec'
    assert '(deny file-write*)' in seen['cmd'][2]
    assert seen['timeout'] == 120 and 'NIM_5' not in seen['env']


def test_idle_collector_refuses_active_mac(monkeypatch):
    monkeypatch.setattr(career_scan, 'available', lambda: True)
    monkeypatch.setattr(idle_policy, 'current_snapshot', lambda: idle_policy.Snapshot(0, True, 0, False))
    monkeypatch.setattr(career_scan, 'run_group', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not execute')))
    assert not career_scan.run(idle=True).ok
