import json
from backbone.proactive import _input_digest

def test_runtime_receipt_changes_invalidate_same_snapshot(tmp_path):
    runtime=tmp_path/'runtime';runtime.mkdir()
    snap=runtime/'collect.json';snap.write_text(json.dumps({'goal':'collect','seq':1}))
    receipt=runtime/'collect-1.md';receipt.write_text('FIRST')
    g={'source_paths':['runtime/collect.json']}
    before=_input_digest(g,tmp_path);receipt.write_text('SECOND')
    assert _input_digest(g,tmp_path)!=before

def test_source_boundaries_cannot_alias_by_redistributing_text(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b';a.write_text('ab');b.write_text('c')
    g={'source_paths':['a','b']};before=_input_digest(g,tmp_path)
    a.write_text('a');b.write_text('bc')
    assert _input_digest(g,tmp_path)!=before

def test_unicode_consumed_character_range_is_fingerprinted(tmp_path):
    p=tmp_path/'source';p.write_text('я'*60000+'A')
    g={'source_paths':['source']};before=_input_digest(g,tmp_path)
    p.write_text('я'*60000+'B')
    assert _input_digest(g,tmp_path)!=before

def test_missing_and_malformed_runtime_inputs_never_created(tmp_path):
    runtime=tmp_path/'runtime';runtime.mkdir()
    g={'source_paths':['runtime/missing.json']};assert _input_digest(g,tmp_path)
    assert not (runtime/'missing.json').exists()
    (runtime/'missing.json').write_text('[]');assert _input_digest(g,tmp_path)
    assert sorted(p.name for p in runtime.iterdir())==['missing.json']


def test_nonregular_receipt_cannot_block_fingerprinting(tmp_path):
    import os
    runtime=tmp_path/'runtime';runtime.mkdir()
    (runtime/'collect.json').write_text(json.dumps({'goal':'collect','seq':1}))
    os.mkfifo(runtime/'collect-1.md')
    assert _input_digest({'source_paths':['runtime/collect.json']},tmp_path)
