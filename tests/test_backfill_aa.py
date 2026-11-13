import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
import backfill_aa as b
from backbone import hook_log


def _fixture(tmp_path, n=6):
    proj = tmp_path / "proj"; proj.mkdir()
    data = tmp_path / "data"; data.mkdir()
    dev, ranks = [], []
    for i in range(n):
        prompt = "please do task number %d with enough length to count" % i
        lines = [{"type": "user", "message": {"content": prompt}, "timestamp": "t%d" % i},
                 {"type": "assistant", "message": {"content": [
                     {"type": "tool_use", "name": "Skill", "input": {"skill": "alpha"}},
                     {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "engineer"}}]}}]
        (proj / ("sess%d.jsonl" % i)).write_text("\n".join(json.dumps(l) for l in lines))
        dev.append({"id": "dev-%d" % i, "prompt": prompt})
        ranks.append({"id": "dev-%d" % i, "top": [["alpha", .9], ["b", .8], ["c", .7], ["d", .6]]})
    dev.append({"id": "dev-r", "prompt": "Another Claude session sent something"})
    ranks.append({"id": "dev-r", "top": [["alpha", 1]]})
    (data / "dev.jsonl").write_text("\n".join(map(json.dumps, dev)))
    (data / "embed_ranks.jsonl").write_text("\n".join(map(json.dumps, ranks)))
    return data, str(proj / "*.jsonl")


def test_replay_receipts_and_outcomes(tmp_path):
    data, pat = _fixture(tmp_path)
    rec, outc = b.replay(str(data), str(data / "embed_ranks.jsonl"), str(tmp_path / "out"), pat)
    assert len(rec) == 6 and all(r["session_id"].startswith("sess") and r["prompt_id"] for r in rec)
    assert all(r["would_surface"] == ["alpha", "b", "c"] for r in rec)
    assert len(outc) == 12 and {o["prompt_id"] for o in outc} == {r["prompt_id"] for r in rec}
    rep = hook_log.report(rec, outc)
    assert sum(a["followed"] for a in rep["arms"].values()) == 6
    assert "followed" in hook_log.format_report(rep)


def test_verdict():
    ins = {"insufficient": True}
    assert "INSUFFICIENT" in b.verdict(ins)
    ok = {"insufficient": False, "treat_minus_holdout_pp": 3.0, "p_value": 0.01}
    assert b.verdict(ok) == "A/A OK"
    assert b.verdict(dict(ok, treat_minus_holdout_pp=20.0, p_value=0.5)) == "A/A OK"
    assert b.verdict(dict(ok, treat_minus_holdout_pp=-20.0, p_value=0.001)) == "A/A SUSPECT"
