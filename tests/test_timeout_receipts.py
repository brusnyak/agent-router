import subprocess
import sys

import pytest

from backbone.core import Backbone, load_config
from backbone.workers import Result
from backbone.workspace import run_group


@pytest.fixture
def router(tmp_path, monkeypatch):
    from backbone import otel
    monkeypatch.setattr(otel, '_TRACER', False)
    cfg = load_config()
    for key, name in [('db', 'runs.db'), ('graph_db', 'graph.db'),
                      ('tickets_dir', 'tickets'), ('runs_dir', 'runs'), ('work_dir', 'work')]:
        cfg[key] = str(tmp_path / name)
    cfg['hooks'] = {}
    cfg['critic'] = {'when': 'never'}
    return Backbone(cfg, env={'NIM_1': 'synthetic'})


def test_timeout_does_not_repeat_same_worker(router, tmp_path, monkeypatch):
    calls = []
    def work(*args):
        calls.append(args)
        return Result(False, 'pi timeout after 1s', 'pi:NIM_1', 'NIM_1', 1000,
                      {'failure_kind': 'timeout', 'retryable': False})
    monkeypatch.setattr(router, '_dispatch', work)
    result = router.run('bounded timeout', worker='nim1', gate='true',
                        cwd=str(tmp_path), isolate=False, prepared=True, use_vault=False)
    assert len(calls) == 1
    assert result['state'] == 'blocked' and result['attempts'] == 1
    assert result['key_slot'] == 'NIM_1'
    assert result['worker_meta']['failure_kind'] == 'timeout'
    assert result['elapsed_ms'] >= 0


def test_actual_gate_failure_can_be_repaired(router, tmp_path, monkeypatch):
    calls = []
    gates = iter([(False, 'missing artifact'), (True, 'artifact accepted')])
    monkeypatch.setattr('backbone.graph.run_gate', lambda *a: next(gates))
    def work(*args):
        calls.append(args)
        return Result(True, 'completed', 'pi:NIM_1', 'NIM_1')
    monkeypatch.setattr(router, '_dispatch', work)
    result = router.run('repair artifact', worker='nim1', gate='fixture gate',
                        cwd=str(tmp_path), isolate=False, prepared=True, use_vault=False)
    assert len(calls) == 2 and result['attempts'] == 2
    assert result['state'] == 'done' and result['gate_passed']


def test_timeout_retains_partial_process_output(tmp_path):
    command = [sys.executable, '-u', '-c',
               'import sys,time; print("checkpoint"); print("diagnostic",file=sys.stderr); time.sleep(10)']
    with pytest.raises(subprocess.TimeoutExpired) as error:
        run_group(command, str(tmp_path), timeout=1)
    assert 'checkpoint' in error.value.output
    assert 'diagnostic' in error.value.stderr


def test_metadata_redacts_keys_loaded_only_into_pool(router, tmp_path, monkeypatch):
    secret = "synthetic-private-token-123456789"
    router.pool.env["NIM_1"] = secret
    monkeypatch.setattr(Backbone, '_dispatch_raw', lambda *args: Result(
        False, "timeout " + secret, "pi:NIM_1", "NIM_1", 1000,
        {"failure_kind": "timeout", "partial_output": "child echoed " + secret}))
    result = router._dispatch("pi:NIM_1", "bounded fixture", str(tmp_path), False, 1)
    assert secret not in result.text
    assert secret not in str(result.meta)
    assert "[REDACTED:key]" in result.meta['partial_output']
