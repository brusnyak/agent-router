"""Hermetic retrieval checks: temporary files/processes and mocked HTTP only."""
import io
import json
from pathlib import Path
import sys
import socket
from unittest.mock import Mock

import pytest

from backbone import retrieval as r


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('PATH', '')
    monkeypatch.setattr(socket.socket, 'connect', Mock(side_effect=AssertionError('network forbidden')))
    monkeypatch.setattr(r, 'urlopen', Mock(side_effect=AssertionError('network forbidden')))


def command(code):
    return [sys.executable, '-c', code]


def test_cmd_parses_scores_and_paths():
    p = r.CmdProvider('fake', {'command': command(
        'print("[1.354] pages/plans/master-plan.md — Master plan (area=[[Ops]], updated=2026-11-17)")')})
    assert p.detect()
    assert p.search('plan', 1) == [r.Hit('pages/plans/master-plan.md', 'Master plan', '', 1.354, 'pages/plans/master-plan.md')]
    assert p.doctor()['ok']


def test_query_remains_one_argument_and_shell_never_runs(tmp_path):
    marker = tmp_path / 'injected'
    query = f'"; touch {marker}; $(echo bad) # {{k}}'
    p = r.CmdProvider('fake', {'command': command(
        'import sys; print("[1] doc.md — " + sys.argv[1])') + ['{q}']})
    assert p.search(query, 1)[0].title == query
    assert not marker.exists()


@pytest.mark.parametrize('code,note', [
    ('raise SystemExit(2)', ('CalledProcessError', 'TimeoutExpired')),
    ('print("nonsense")', 'ValueError'),
    ('import time; time.sleep(1)', 'TimeoutExpired'),
])
def test_command_failures_are_visible(code, note):
    p = r.CmdProvider('bad', {'command': command(code), 'timeout_s': 0.05})
    assert p.search('query', 5) == []
    assert not p.doctor()['ok']
    expected = note if isinstance(note, tuple) else [note]
    assert any(n in p.doctor()['note'] for n in expected)
    assert p.doctor()['latency_s'] >= 0


def test_missing_command_and_recovery():
    p = r.CmdProvider('missing', {'command': ['absent-command']})
    assert not p.detect()
    assert p.search('q', 1) == []
    assert not p.doctor()['ok']
    p.params['command'] = command('print("[1] a.md — A")')
    assert p.search('q', 1)
    assert p.doctor()['ok']


def test_doctor_probes_command():
    p = r.CmdProvider('fake', {'command': command('print("garbage")')})
    assert not p.doctor()['ok']


def test_http_url_encoding_json_and_failure(monkeypatch):
    opener = Mock(return_value=io.BytesIO(json.dumps([dict(id='a', title='A', text='body', score=2)]).encode()))
    monkeypatch.setattr(r, 'urlopen', opener)
    p = r.HttpProvider('web', {'url': 'https://example.invalid/search?q={q}&k={k}'})
    assert p.detect()
    assert p.search('a &/b?', 2) == [r.Hit('a', 'A', 'body', 2, 'a')]
    assert opener.call_args.args[0] == 'https://example.invalid/search?q=a%20%26%2Fb%3F&k=2'
    opener.side_effect = TimeoutError('offline')
    assert p.search('q', 2) == []
    assert 'offline' in p.doctor()['note']


@pytest.mark.parametrize('payload', ['{}', 'null', 'bad json', '[{"id":"a","score":"NaN"}]'])
def test_malformed_http(monkeypatch, payload):
    monkeypatch.setattr(r, 'urlopen', lambda *a, **kw: io.BytesIO(payload.encode()))
    p = r.HttpProvider('bad', {'url': 'http://example.invalid/{q}'})
    assert p.search('q') == []
    # An empty object is a valid empty results envelope.
    assert p.doctor()['ok'] == (payload == '{}')


def test_builtin_wraps_rag_and_maps_vault_path():
    rag = Mock()
    rag.search.return_value = [dict(id='vault:a', name='A', description='body', score=1,
                                  source='vault', meta={'path': 'pages/a.md'})]
    p = r.BuiltinProvider(rag=rag)
    assert p.detect()
    assert p.search('a', 1) == [r.Hit('vault:a', 'A', 'body', 1, 'pages/a.md')]
    rag.search.assert_called_once_with('a', k=1)
    rag.search.side_effect = RuntimeError('db unavailable')
    assert p.search('a') == []
    assert not p.doctor()['ok']


def test_builtin_missing_database_does_not_create(tmp_path):
    path = tmp_path / 'missing.db'
    p = r.BuiltinProvider(params={'db': str(path)})
    assert not p.detect()
    assert p.search('q') == []
    assert not path.exists()
    assert not p.doctor()['ok']


def test_builtin_real_local_rag(tmp_path):
    from backbone.db import connect
    from backbone import library
    path = tmp_path / 'library.db'
    con = connect(str(path))
    library.upsert(con, 'vault', 'test', 'portable retrieval', 'portable retrieval',
                   meta={'path': 'pages/test.md'}, source='vault')
    con.commit()
    p = r.BuiltinProvider(params={'db': str(path)})
    hits = p.search('portable', 5)
    assert hits and hits[0].source == 'pages/test.md', p.doctor()


MCP = '''
import json, sys
initialized = False
for line in sys.stdin:
    message = json.loads(line)
    method = message['method']
    if method == 'initialize':
        result = {'protocolVersion': message['params']['protocolVersion'], 'capabilities': {'tools': {}}}
    elif method == 'notifications/initialized':
        initialized = True
        continue
    elif method == 'tools/list':
        assert initialized
        result = {'tools': [{'name': 'find'}]}
    elif method == 'tools/call':
        assert initialized
        assert message['params']['name'] == 'find'
        args = message['params']['arguments']
        assert args['limit'] == 2 and args['scope'] == 'all'
        result = {'content': [{'type':'text', 'text': json.dumps([{'id':'a.md', 'title':args['q']}])}]}
    print(json.dumps({'jsonrpc':'2.0', 'method':'notifications/progress', 'params':{}}), flush=True)
    print(json.dumps({'jsonrpc':'2.0', 'id':message['id'], 'result':result}), flush=True)
'''


def mcp(code=MCP, **params):
    return r.McpStdioProvider('mcp', dict(command=command(code), tool='find', timeout_s=1,
                                       query_arg='q', k_arg='limit', arguments={'scope': 'all'}, **params))


def test_mcp_lifecycle_and_search():
    p = mcp()
    assert p.detect()
    assert p.doctor()['ok']
    assert p.search('hello', 2) == [r.Hit('a.md', 'hello', '', 0, 'a.md')]


@pytest.mark.parametrize('code', [
    'print("not json", flush=True)',
    'import time; time.sleep(2)',
    'raise SystemExit(1)',
    MCP.replace("'name': 'find'", "'name': 'other'"),
])
def test_mcp_doctor_failure(code):
    p = mcp(code)
    p.params['timeout_s'] = 0.05
    assert not p.doctor()['ok']
    assert p.doctor()['note'] != 'not checked'


@pytest.mark.parametrize('result', [
    "{'structuredContent': {'hits': [{'id': 'a.md'}]}}",
    "{'content': [{'type': 'text', 'text': '[1] a.md — A'}]}",
])
def test_mcp_result_formats(result):
    code = MCP.replace("{'content': [{'type':'text', 'text': json.dumps([{'id':'a.md', 'title':args['q']}])}]}", result)
    assert mcp(code).search('q', 2)[0].id == 'a.md'


@pytest.mark.parametrize('result', ["{'isError': True}", "{'content': [{'type':'text', 'text':'malformed'}]}"])
def test_mcp_tool_errors(result):
    code = MCP.replace("{'content': [{'type':'text', 'text': json.dumps([{'id':'a.md', 'title':args['q']}])}]}", result)
    p = mcp(code)
    assert p.search('q', 2) == []
    assert not p.doctor()['ok']


def test_config_load_enablement_and_invalid_type(tmp_path):
    path = tmp_path / 'retrieval.yaml'
    path.write_text('''providers:
  - name: enabled
    type: cmd
    enabled: true
    params:
      command: ["python3", "-c", "print('ok')"]
  - name: disabled
    type: http
    enabled: false
    params:
      url: "http://invalid/#fragment" # comment
  - type: unknown
    enabled: true
''')
    registry = r.Registry(path)
    assert [p.name for p in registry.providers] == ['enabled']
    assert registry.notes
    assert r.load_yaml(path)['providers'][1]['params']['url'].endswith('#fragment')
    assert not r.Registry(tmp_path / 'absent').providers
    path.write_text('providers:\n   broken line')
    assert r.Registry(path).doctor()['notes']


def test_rrf_merges_duplicates_ignores_raw_scores():
    a, b, c = [r.Hit(x, x, '', score, x) for x, score in [('a', 0), ('b', 999), ('c', 1)]]
    p1 = Mock(name='p1', search=Mock(return_value=[a, b, a]))
    p2 = Mock(name='p2', search=Mock(return_value=[b, c]))
    reg = r.Registry(providers=[p1, p2])
    hits = reg.search_all('q', 3)
    assert [h.id for h in hits] == ['b', 'a', 'c']
    assert hits[0].score == pytest.approx(1/62 + 1/61)
    assert hits[1].score == pytest.approx(1/61)
    assert a.score == 0
    assert reg.search_all('q', 0) == []


def test_broken_provider_does_not_hide_healthy_one():
    bad = r.CmdProvider('bad', {'command': ['missing']})
    good = r.CmdProvider('good', {'command': command('print("[1] a — A")')})
    reg = r.Registry(providers=[bad, good])
    assert reg.search_all('q')[0].id == 'a'
    assert not reg.doctor()['providers']['bad']['ok']


def test_context_pack_limits_and_sources(tmp_path):
    anchor = tmp_path / 'anchor.md'
    anchor.write_text(''.join(f'LINE-{i}\n' for i in range(80)))
    projects = tmp_path / 'projects.yaml'
    projects.write_text(f'projects:\n  - id: example\n    path: "{tmp_path}"\n    anchors:\n      - anchor.md\n      - missing.md\n')
    p = Mock(search=Mock(return_value=[r.Hit('hit', 'Title', 'x'*9000, 1, 'pages/hit.md')]))
    reg = r.Registry(providers=[p], projects_path=projects)
    pack = reg.context_pack('task', 'example')
    assert pack.startswith('checked_at: ')
    assert len(pack) == 6000
    assert f'source: {anchor}' in pack
    assert 'LINE-39\n' in pack and 'LINE-40\n' not in pack
    assert 'source: pages/hit.md' in pack
    assert 'unavailable:' in pack
    p.search.assert_called_once_with('task', 5)
    assert reg.context_pack('task', 'unknown').startswith('checked_at: ')


def test_context_pack_without_anchors(tmp_path):
    projects = tmp_path / 'projects.yaml'
    projects.write_text('projects:\n  - id: empty\n')
    assert r.Registry(providers=[], projects_path=projects).context_pack('q', 'empty').startswith('checked_at:')


def test_discovery_proposes_only(monkeypatch, tmp_path):
    script = tmp_path / 'memory-vault/scripts/vector_memory/query.py'
    script.parent.mkdir(parents=True)
    script.write_text('')
    monkeypatch.setattr(r.shutil, 'which', lambda name: '/fake/' + name)
    entries = r.discover()
    assert {e['name'] for e in entries} == {'vault', 'qmd', 'basic-memory'}
    assert all(e['enabled'] is False for e in entries)
    assert not (tmp_path / 'config').exists()


def test_shipped_configs_and_golden_metrics():
    from eval.golden_recall import evaluate
    entries = r.load_yaml(r.ROOT / 'config/golden_recall.yaml')
    assert len(entries) == 10
    config = r.load_yaml(r.ROOT / 'config/retrieval.yaml')
    assert len(config['providers']) == 4
    reg = r.Registry(providers=[])
    assert evaluate(reg, entries) == {'queries': 10, 'hit@1': 0, 'hit@5': 0}
    reg = Mock()
    reg.search_all.return_value = [r.Hit('other', '', '', 0, 'other'), r.Hit('vision', '', '', 0, 'vision')]
    assert evaluate(reg, [entries[1]]) == {'queries': 1, 'hit@1': 0, 'hit@5': 1}


@pytest.mark.parametrize('args', [['doctor'], ['search', 'query', '-k', '2'], ['pack', 'task', '--project', 'x'], ['discover']])
def test_cli_registration(monkeypatch, capsys, args):
    from backbone.cli import main
    registry = r.Registry(providers=[])
    monkeypatch.setattr(r, 'Registry', Mock(return_value=registry))
    with pytest.raises(SystemExit) as exit:
        main(['retrieval'] + args)
    assert exit.value.code in (None, 0)
    assert capsys.readouterr().out


def test_large_anchor_does_not_hide_hit_provenance(tmp_path):
    (tmp_path / 'anchor.md').write_text('a' * 10000)
    projects = tmp_path / 'projects.yaml'
    projects.write_text(f'projects:\n  - id: x\n    path: "{tmp_path}"\n    anchors: ["anchor.md"]\n')
    hits = [r.Hit(str(i), 'Title', 'x' * 10000, 1, f'pages/{i}.md') for i in range(5)]
    provider = Mock(search=Mock(return_value=hits))
    pack = r.Registry(providers=[provider], projects_path=projects).context_pack('q', 'x')
    assert len(pack) <= 6000
    assert all(f'source: pages/{i}.md' in pack for i in range(5))


def test_mcp_jsonrpc_error():
    code = MCP.replace("'result':result", "'error':{'code':-1, 'message':'failed'}")
    provider = mcp(code)
    assert provider.search('q', 2) == []
    assert 'MCP error' in provider.doctor()['note']
