import json
import os
import subprocess
import sys
import pytest

from backbone import keys


def test_separate_processes_do_not_all_take_preferred_key(tmp_path, monkeypatch):
    state = str(tmp_path / 'keys.json')
    monkeypatch.setattr(keys, 'STATE_FILE', state)
    pool = keys.KeyPool(['NIM_1', 'NIM_2'], env={'NIM_1': 'fake', 'NIM_2': 'fake'})
    code = '''
import sys
from backbone import keys
keys.STATE_FILE = sys.argv[1]
p = keys.KeyPool(['NIM_1','NIM_2'], env={'NIM_1':'fake','NIM_2':'fake'})
with p.lease(prefer='NIM_1') as name:
    print(name, flush=True)
'''
    with pool.lease(prefer='NIM_1') as first:
        result = subprocess.run([sys.executable, '-c', code, state],
                                capture_output=True, text=True, check=True, timeout=10)
        assert first == 'NIM_1' and result.stdout.strip() == 'NIM_2'
    assert all(not v.get('leases') for v in json.loads((tmp_path / 'keys.json').read_text()).values())


def test_dead_process_claim_does_not_block_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, 'STATE_FILE', str(tmp_path / 'keys.json'))
    # Obtain an actual PID which has already exited.
    proc = subprocess.Popen([sys.executable, '-c', 'pass'])
    proc.wait(timeout=5)
    keys._shared_save({'NIM_1': {'leases': {'dead': proc.pid}, 'ts': 0}})
    assert keys.shared_claim('NIM_1', 'new', ['NIM_1'], limit=1)
    keys.shared_release('NIM_1', 'new')


def test_same_process_independent_pools_respect_shared_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, 'STATE_FILE', str(tmp_path / 'keys.json'))
    assert keys.shared_claim('NIM_1', 'first', ['NIM_1'], limit=1)
    assert not keys.shared_claim('NIM_1', 'second', ['NIM_1'], limit=1)
    keys.shared_release('NIM_1', 'first')
    assert keys.shared_claim('NIM_1', 'second', ['NIM_1'], limit=1)
    keys.shared_release('NIM_1', 'second')


def test_claim_failure_releases_local_semaphore(tmp_path, monkeypatch):
    monkeypatch.setattr(keys, 'STATE_FILE', str(tmp_path / 'keys.json'))
    pool = keys.KeyPool(['NIM_1'], env={'NIM_1': 'fake'}, max_concurrent=1)
    original = keys.shared_claim
    def fail(*args, **kwargs):
        raise OSError('fixture write failure')
    monkeypatch.setattr(keys, 'shared_claim', fail)
    with pytest.raises(OSError):
        with pool.lease():
            pytest.fail('lease must fail before callback')
    monkeypatch.setattr(keys, 'shared_claim', original)
    with pool.lease() as name:
        assert name == 'NIM_1'


def test_rpm_reservation_is_atomic_across_concurrent_claims(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(keys, 'STATE_FILE', str(tmp_path / 'keys.json'))
    def claim(index):
        return keys.shared_claim('NIM_1', str(index), ['NIM_1'], rpm_limit=2)
    with ThreadPoolExecutor(max_workers=3) as executor:
        assert sum(executor.map(claim, range(3))) == 2
    assert keys.shared_count('NIM_1') == 2
    for index in range(3):
        keys.shared_release('NIM_1', str(index))
