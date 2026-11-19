import json
import subprocess
from unittest.mock import patch
import pytest
from backbone.model_policy import _reported_model_matches
from backbone.workers import ClaudeWorker

@pytest.mark.parametrize('requested,reported,expected',[
 ('',[],True),('haiku',['claude-haiku-5-5'],True),('HAIKU',['CLAUDE-HAIKU-5-5'],True),
 ('haiku',['claude-sonnet-5-5'],False),('haiku',['claude-haiku-5-5','claude-sonnet-5-5'],False),
 ('haiku',[],False),('haiku',{},False),('haiku',[None],False),('haiku',['not-haiku'],False),
 ('haiku',[''],False),(None,[],False),('sonnet[1m]',['claude-sonnet-5-5'],True),
 ('claude-haiku-5-5',['claude-haiku-5-5'],True),
 ('claude-haiku-5-5',['claude-haiku-4-5'],False),
 ('claude-sonnet-5-5[1m]',['claude-sonnet-5-5[1m]'],True)])
def test_reported_model_gate(requested,reported,expected):
 assert _reported_model_matches(requested,reported) is expected

@pytest.mark.parametrize('usage',[None,{},[],{'claude-sonnet-5-5':{}}])
def test_mismatched_or_missing_model_telemetry_cannot_be_success(tmp_path,usage):
 raw=json.dumps({'result':'THIS OUTPUT MUST NOT BE ACCEPTED','modelUsage':usage,'total_cost_usd':0.1})
 with patch('backbone.workers._run',return_value=subprocess.CompletedProcess([],0,raw,'')) as run:
  result=ClaudeWorker({'model':'haiku'}).run('boundedfixture',str(tmp_path))
 assert run.call_count==1 and not result.ok
 assert result.meta['failure_kind']=='model_mismatch' and result.meta['retryable'] is False
 assert result.meta['requested_model']=='haiku' and result.meta['cost_usd']==0.1
 assert 'THIS OUTPUT' not in result.text
