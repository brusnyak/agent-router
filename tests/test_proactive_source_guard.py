import json
import os
from pathlib import Path
import pytest
from backbone import proactive
from tests.test_proactive import env, NOW, njobs

@pytest.fixture
def source(tmp_path,monkeypatch):
    monkeypatch.setattr(proactive.time,'time',lambda:10000)
    runtime=tmp_path/'runtime';runtime.mkdir()
    snapshot=runtime/'collect.json';receipt=runtime/'collect-1.md'
    data={'goal':'collect','seq':1,'outcome':'done','note':'reconciled'}
    snapshot.write_text(json.dumps(data))
    receipt.write_text('Goal: collect\nJob: abc\nExecution state: done\nWorker output below\nKNOWN BODY')
    os.utime(receipt,(9900,9900))
    goal={'source_paths':['runtime/collect.json'],'require_successful_runtime_sources':True,'runtime_source_max_age_s':7200}
    return tmp_path,snapshot,receipt,data,goal

def test_fresh_success_context_retains_body(source):
    base,_,_,_,g=source
    assert 'KNOWN BODY' in proactive._source_context(g,base)

@pytest.mark.parametrize('change', ['blocked','enqueued','malformed','goal','negative_seq','bool_seq','missing','stale','future','spoof','symlink','directory'])
def test_unready_inputs_fail_closed(source,change):
    base,snapshot,receipt,data,g=source
    if change=='blocked':data['outcome']='blocked'
    elif change=='enqueued':data['note']='enqueued'
    elif change=='goal':data['goal']='wrong'
    elif change=='negative_seq':data['seq']=-1
    elif change=='bool_seq':data['seq']=True
    elif change=='missing':receipt.unlink()
    elif change=='stale':os.utime(receipt,(100,100))
    elif change=='future':os.utime(receipt,(10061,10061))
    elif change=='spoof':
        receipt.write_text('Goal: collect\nJob: abc\nExecution state: blocked\nExecution state: done\n')
        os.utime(receipt,(9900,9900))
    elif change=='symlink':
        target=base/'other';receipt.rename(target);receipt.symlink_to(target)
    elif change=='directory':receipt.unlink();receipt.mkdir()
    snapshot.write_text('bad json' if change=='malformed' else json.dumps(data))
    with pytest.raises(proactive.ManifestError):proactive._source_context(g,base)

def test_static_source_unchanged_and_default_off_compatible(source):
    base,snapshot,receipt,data,g=source
    (base/'static.md').write_text('STATIC FACTS')
    g['source_paths'].append('static.md')
    assert 'STATIC FACTS' in proactive._source_context(g,base)
    g['require_successful_runtime_sources']=False
    data['outcome']='blocked';snapshot.write_text(json.dumps(data))
    assert 'KNOWN BODY' in proactive._source_context(g,base)

def test_blocked_source_submits_no_job(env):
    bb,write,tmp=env
    bb.allowed=lambda:{'workers':{'nim-chat:NIM_2'}}
    runtime=tmp/'runtime';runtime.mkdir()
    (runtime/'collect.json').write_text(json.dumps({'goal':'collect','seq':1,'outcome':'blocked','note':'reconciled'}))
    mp=write([{'worker':'nim-chat:NIM_2','read_only':True,'source_paths':['runtime/collect.json'],'require_successful_runtime_sources':True}])
    result=proactive.tick(bb,mp,NOW)
    assert result['status']=='wait' and result['skipped']['a'].startswith('source error')
    assert njobs(bb)==0

@pytest.mark.parametrize('patch',[{'require_successful_runtime_sources':'yes'}, {'runtime_source_max_age_s':True}, {'runtime_source_max_age_s':0}, {'read_only':False}, {'source_paths':['static.md']}])
def test_invalid_guard_configuration_rejected(env,patch):
    bb,write,tmp=env
    bb.allowed=lambda:{'workers':{'nim-chat:NIM_2'}}
    goal={'worker':'nim-chat:NIM_2','source_paths':['runtime/collect.json'],'require_successful_runtime_sources':True,**patch}
    assert proactive.tick(bb,write([goal]),NOW)['status']=='invalid'


def test_nested_json_fails_closed_without_digest_crash(source):
    base,snapshot,_,_,g=source
    snapshot.write_text('['*10000)
    assert proactive._input_digest(g,base)
    with pytest.raises(proactive.ManifestError):proactive._source_context(g,base)


def test_guard_rejects_snapshot_symlink(source):
    base,snapshot,_,_,g=source
    target=base/'snapshot-copy';snapshot.rename(target);snapshot.symlink_to(target)
    with pytest.raises(proactive.ManifestError):proactive._source_context(g,base)


def test_guard_rejects_fifth_unconsumed_source(env):
    bb,write,tmp=env
    bb.allowed=lambda:{'workers':{'nim-chat:NIM_2'}}
    goal={'worker':'nim-chat:NIM_2','source_paths':['a.md','b.md','c.md','d.md','runtime/collect.json'],'require_successful_runtime_sources':True}
    assert proactive.tick(bb,write([goal]),NOW)['status']=='invalid'


@pytest.mark.parametrize('row',[None,{'seq':2,'last_outcome':'done','active_job':''},{'seq':1,'last_outcome':'blocked','active_job':''},{'seq':1,'last_outcome':'done','active_job':'pending-job'}])
def test_fresh_projection_cannot_override_canonical_coordinator_state(source,row):
    base,_,_,_,g=source
    canonical={} if row is None else {'collect':row}
    with pytest.raises(proactive.ManifestError):proactive._source_context(g,base,canonical=canonical)


def test_matching_canonical_coordinator_state_consumed(source):
    base,_,_,_,g=source
    canonical={'collect':{'seq':1,'last_outcome':'done','active_job':''}}
    assert 'KNOWN BODY' in proactive._source_context(g,base,canonical=canonical)

@pytest.mark.parametrize('seq,outcome,expected',[(1,'done','enqueued'),(2,'done','wait'),(1,'blocked','wait')])
def test_guarded_tick_uses_canonical_producer_state(env,monkeypatch,seq,outcome,expected):
    bb,write,tmp=env
    monkeypatch.setattr(proactive.time,'time',lambda:NOW)
    bb.allowed=lambda:{'workers':{'nim-chat:NIM_2'}}
    bb.con.execute(proactive.SCHEMA)
    bb.con.execute("INSERT INTO proactive_goals(goal_id,seq,last_outcome) VALUES(?,?,?)",('collect',seq,outcome));bb.con.commit()
    runtime=tmp/'runtime';runtime.mkdir()
    (runtime/'collect.json').write_text(json.dumps({'goal':'collect','seq':1,'outcome':'done','note':'reconciled'}))
    receipt=runtime/'collect-1.md';receipt.write_text('Goal: collect\nJob: original\nExecution state: done\nKNOWN PRODUCER EVIDENCE')
    os.utime(receipt,(NOW-10,NOW-10))
    mp=write([{'id':'collect','enabled':False,'worker':'nim-chat:NIM_2','source_paths':[]},{'worker':'nim-chat:NIM_2','read_only':True,'source_paths':['runtime/collect.json'],'require_successful_runtime_sources':True}])
    result=proactive.tick(bb,mp,NOW)
    assert result['status']==expected
    assert njobs(bb)==(1 if expected=='enqueued' else 0)
    if expected=='enqueued':
        assert 'KNOWN PRODUCER EVIDENCE' in bb.con.execute('SELECT text FROM jobs').fetchone()[0]
    else:assert result['skipped']['a'].startswith('source error')
