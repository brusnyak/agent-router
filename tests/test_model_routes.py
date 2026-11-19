import json
import subprocess
from unittest.mock import patch
from backbone.workers import ClaudeWorker, KiloWorker

def test_haiku_is_explicit_and_actual_model_reported(tmp_path):
    result = subprocess.CompletedProcess([], 0, json.dumps({'result':'ok','modelUsage':{'claude-haiku-4-5':{}},'num_turns':1}), '')
    with patch('backbone.workers._run', return_value=result) as run, patch.dict('os.environ', {'ANTHROPIC_API_KEY':'synthetic','ANTHROPIC_BASE_URL':'https://example.test'}):
        receipt=ClaudeWorker({'model':'haiku'}).run('Reply OK', str(tmp_path), read_only=True)
    argv, _, env, _ = run.call_args.args
    assert argv[argv.index('--model')+1] == 'haiku'
    assert '--strict-mcp-config' in argv
    assert argv[argv.index('--permission-mode')+1] == 'plan'
    assert 'ANTHROPIC_API_KEY' not in env and 'ANTHROPIC_BASE_URL' not in env
    assert receipt.meta['reported_models'] == ['claude-haiku-4-5']

def test_empty_model_preserves_cli_default(tmp_path):
    with patch('backbone.workers._run', return_value=subprocess.CompletedProcess([],0,'{"result":"ok"}','')) as run:
        assert ClaudeWorker({}).run('OK',str(tmp_path)).ok
    assert '--model' not in run.call_args.args[0]

def test_kilo_uses_run_subcommand_and_key_only_in_environment(tmp_path):
    with patch('backbone.workers._run', return_value=subprocess.CompletedProcess([],0,'OK','')) as run:
        assert KiloWorker({}).run('OK',str(tmp_path),key='NIM_1',api_key='synthetic-key').ok
    argv, _, env, _ = run.call_args.args
    assert argv[:2] == ['kilo','run']
    assert 'synthetic-key' not in ' '.join(argv)
    assert env['API_KEY'] == 'synthetic-key'
