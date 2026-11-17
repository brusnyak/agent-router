"""End-to-end evaluation, skill activation, hooks, and loop tests.

Covers:
- Shadow evaluation thresholds, coverage, top-1/top-3 (eval/shadow_eval.py)
- Skill activation follow rates across treat vs holdout arms (backbone/hook_log.py)
- Hook heavy-task detection and nudge selection (backbone/hook.py)
- Enrichment loops: idempotency, margin-gate abstention, retry stability (eval/shadow_enrich.py)
- Evaluation availability for skill activation: no prompt text leaks into reports/receipts
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
import shadow_eval as se  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backbone import hook_log as hl  # noqa: E402
from backbone import hook  # noqa: E402
from eval import shadow_enrich as senr  # noqa: E402


def _w(p, rows):
    p.write_text("\n".join(json.dumps(r) for r in rows))


def _sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def _setup_eval(tmp_path):
    # norm() maps 'kind:name:hash' -> 'name'; silver must be bare name to match
    _w(tmp_path / "silver.jsonl", [
        {"id": "a", "split": "dev", "silver": "x"},
        {"id": "b", "split": "dev", "silver": "x"},
        {"id": "c", "split": "test", "silver": "x"},
    ])
    _w(tmp_path / "router_ranks.jsonl", [
        {"id": "a", "top": [["skill:x:h1", 0.9], ["y", 0.4]]},   # normed [x, y], margin 0.5
        {"id": "b", "top": [["y", 0.5], ["z", 0.5], ["skill:x", 0.1]]},  # normed [y, z, x], margin 0.0
        {"id": "c", "top": [["y", 0.9], ["z", 0.4]]}])


# ------------------------------------------------------------------ evaluation

def test_evaluation_abstains_below_threshold_and_coverage(tmp_path):
    _setup_eval(tmp_path)
    rows = se.load("router", "dev", tmp_path)
    assert len(rows) == 2
    e = se.evaluate(rows, 0.1)   # keep a (margin 0.5), drop b (margin 0.0)
    assert e["coverage"] == 0.5 and e["top1"] == 1.0
    e0 = se.evaluate(rows, 0)    # keep both
    assert e0["coverage"] == 1.0 and e0["top1"] == 0.5 and e0["top3"] == 1.0


def test_evaluation_tune_dev_only_excludes_test(tmp_path):
    _setup_eval(tmp_path)
    with open(tmp_path / "silver.jsonl", "a") as f:
        f.write("\n" + json.dumps({"id": "d", "split": "dev", "silver": "x"}))
    with open(tmp_path / "router_ranks.jsonl", "a") as f:
        f.write("\n" + json.dumps({"id": "d", "top": [["y", 0.5], ["z", 0.5], ["w", 0.1]]}))
    assert se.main(["--source", "router", "--tune", "--thresholds", "0,0.1"], tmp_path) == 0
    g = json.loads((tmp_path / "gate.json").read_text())
    assert g["T"] == 0.1
    assert g["dev"]["n"] == 3  # test row excluded from tuning


def test_evaluation_test_split_refused_without_final(tmp_path):
    _setup_eval(tmp_path)
    assert se.main(["--source", "router", "--split", "test"], tmp_path) == 2
    assert se.main(["--source", "router", "--split", "test", "--final"], tmp_path) == 0


def test_evaluation_threshold_boundary_inclusive(tmp_path):
    # margin exactly equal to threshold should still pass (>=)
    _w(tmp_path / "silver.jsonl", [{"id": "a", "split": "dev", "silver": "x"}])
    _w(tmp_path / "router_ranks.jsonl", [
        {"id": "a", "top": [["skill:x:h1", 0.9], ["y", 0.4]]}])  # normed [x, y], margin 0.5 exact
    rows = se.load("router", "dev", tmp_path)
    e = se.evaluate(rows, 0.5)  # margin == threshold, kept (>=)
    assert e["coverage"] == 1.0 and e["top1"] == 1.0


# ---------------------------------------------------------------- skill activation

def _rc(i, arm, sid="s", ts=1, sel=("a",), ws=()):
    return {"receipt_id": "r%s" % i, "ts": ts, "arm": arm, "selected": list(sel),
            "would_surface": list(ws), "session_id": sid, "prompt_id": "p%s" % i}


def _oc(skill, sid="s", pid=None, ts=2):
    return {"ts": ts, "skill": skill, "session_id": sid, "prompt_id": pid, "tool_use_id": "t"}


def test_skill_follow_rate_treat_above_holdout(tmp_path):
    receipts = [_rc(i, "treat", sid="t%d" % i) for i in range(20)] + \
               [_rc(100 + i, "holdout", sid="h%d" % i) for i in range(20)]
    outcomes = [_oc("a", sid="t%d" % i, pid="p%d" % i) for i in range(15)] + \
               [_oc("a", sid="h%d" % i, pid="p%d" % (100 + i)) for i in range(5)]
    rep = hl.report(receipts, outcomes)
    assert not rep["insufficient"]
    assert rep["arms"]["treat"]["rate"] == 0.75
    assert rep["arms"]["holdout"]["rate"] == 0.25
    assert abs(rep["treat_minus_holdout_pp"] - 50.0) < 1e-9
    assert 0 < rep["p_value"] < 0.01


def test_skill_follow_uses_would_surface(tmp_path):
    # followed requires skill in would_surface
    r_holdout = _rc(1, "holdout", ws=("a",))
    assert hl.followed(r_holdout, [_oc("a", pid="p1")])
    r_treat = _rc(1, "treat", ws=("a",))
    assert hl.followed(r_treat, [_oc("a", pid="p1")])
    r_no_surface = _rc(1, "treat", sel=(), ws=())
    assert not hl.followed(r_no_surface, [_oc("a", pid="p1")])


def test_skill_activation_insufficient_data(tmp_path):
    rep = hl.report([_rc(1, "treat"), _rc(2, "holdout")], [])
    assert rep["insufficient"]
    assert rep["treat_minus_holdout_pp"] is None
    assert "n/a" in hl.format_report(rep)


# -------------------------------------------------------------------- hooks

def test_hook_heavy_detection_edge_cases():
    # needs >= 2 heavy keywords OR length >= 900
    assert hook.is_heavy("refactor the whole repo and migrate all files") is True
    assert hook.is_heavy("x" * 900) is True
    assert hook.is_heavy("hi") is False
    assert hook.is_heavy("fix the typo in README") is False


def test_hook_nudge_only_heavy_treat_prompts(monkeypatch):
    monkeypatch.delenv("MR_ORCH_DISPATCH", raising=False)
    assert not hook.decide({"prompt": "fix the typo in README", "session_id": "x1"})["selected"]
    heavy = "refactor the whole repo and migrate all files across the repo"
    r = hook.decide({"prompt": heavy, "session_id": "sid-treat", "prompt_id": "p1"})
    assert r["arm"] in ("treat", "holdout")  # deterministic by session hash
    if r["arm"] == "treat":
        assert "heavy-nudge" in r["selected"]


def test_hook_no_raw_prompt_in_receipt():
    secret = "SECRET-PROMPT-TEXT-12345"
    r = hook.decide({"prompt": secret, "session_id": "s", "prompt_id": "p"})
    assert secret not in json.dumps(r)
    assert len(r["prompt_hash"]) == 64


def test_hook_machine_turn_and_lane_child_bypass():
    assert hook.decide({"prompt": "Another Claude session sent x", "session_id": "s"})["mode"] == "machine-turn"
    assert hook.decide({"prompt": "<task-notification>y", "session_id": "s"})["mode"] == "machine-turn"
    os.environ["MR_ORCH_DISPATCH"] = "1"
    try:
        assert hook.decide({"prompt": "please refactor this module now", "session_id": "s"})["mode"] == "lane-child"
    finally:
        del os.environ["MR_ORCH_DISPATCH"]


# -------------------------------------------------------------------- loops

def _make_receipt(tmp_path, content, mode="shadow"):
    """Write a prompt transcript file whose hash matches the receipt.

    find_prompt globs base/*/{session_id}.jsonl, so we need one extra dir level.
    """
    proj = tmp_path / "projects" / "s1"
    proj.mkdir(parents=True)
    (proj / "s1.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n")
    rec = tmp_path / "r.jsonl"
    rec.write_text(json.dumps({"receipt_id": "a", "mode": mode, "would_surface": [],
                               "session_id": "s1", "prompt_hash": _sha(content)}) + "\n")
    return tmp_path / "projects", rec


def test_enrichment_idempotent_loop(tmp_path):
    base, rec = _make_receipt(tmp_path, "PROMPT")
    out = tmp_path / "o.jsonl"
    ret = lambda q: [("x", 0.9), ("y", 0.5)]
    todo, rows1 = senr.enrich(rec, out, ret, projects=str(base), T=0.0)
    assert len(rows1) == 1 and rows1[0]["would_surface"] == ["x", "y"]
    with open(out, "a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows1)
    todo2, rows2 = senr.enrich(rec, out, ret, projects=str(base), T=0.0)
    assert rows2 == []  # idempotent loop break: nothing left to enrich


def test_enrichment_margin_gate_abstains_loop(tmp_path):
    base, rec = _make_receipt(tmp_path, "PROMPT")
    out = tmp_path / "o.jsonl"
    _, rows = senr.enrich(rec, out, lambda q: [("x", 0.6), ("y", 0.55)], projects=str(base), T=0.2)
    assert rows[0]["would_surface"] == [] and rows[0]["abstention"] == "margin"


def test_enrichment_no_prompt_text_leaks(tmp_path):
    base, rec = _make_receipt(tmp_path, "SECRET-LEAK-TEST")
    out = tmp_path / "o.jsonl"
    senr.enrich(rec, out, lambda q: [("x", 0.9)], projects=str(base), T=0.0)
    out_text = out.read_text() if out.exists() else ""
    assert "SECRET-LEAK-TEST" not in out_text


def test_hook_log_cli_report_json(tmp_path):
    rp, op = tmp_path / "r.jsonl", tmp_path / "o.jsonl"
    rp.write_text(json.dumps(_rc(1, "treat")) + "\nbad\n")
    hl.append_outcome(str(op), "a", "s", "p1", "t")
    out = subprocess.run([sys.executable, "-m", "backbone.hook_log", "report", "--json",
                          "--receipts", str(rp), "--outcomes", str(op)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    assert d["bad_lines"] == 1
    assert d["arms"]["treat"]["followed"] == 1
