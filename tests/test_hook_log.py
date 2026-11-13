import json, subprocess, sys
from backbone import hook_log as hl


def rc(i, arm, sid="s", ts=1, sel=("a",), ws=()):
    return {"receipt_id": "r%s" % i, "ts": ts, "arm": arm, "selected": list(sel),
            "would_surface": list(ws), "session_id": sid, "prompt_id": "p%s" % i}


def oc(skill, sid="s", pid=None, ts=2):
    return {"ts": ts, "skill": skill, "session_id": sid, "prompt_id": pid, "tool_use_id": "t"}


def test_join_by_prompt_id():
    r = [rc(1, "treat", ts=1), rc(2, "treat", ts=5)]
    j, sk = hl.join(r, [oc("a", pid="p1", ts=9)])
    assert list(j) == ["r1"] and sk == 0


def test_join_fallback_session_latest_before():
    r = [rc(1, "treat", ts=1), rc(2, "treat", ts=3), rc(3, "treat", ts=8)]
    j, _ = hl.join(r, [oc("a", ts=5)])
    assert list(j) == ["r2"]


def test_no_session_skipped():
    j, sk = hl.join([rc(1, "treat")], [oc("a", sid=None, pid="p1")])
    assert not j and sk == 1


def test_followed_uses_would_surface():
    assert hl.followed(rc(1, "holdout", sel=(), ws=("w",)), [oc("w")])
    assert not hl.followed(rc(1, "treat"), [oc("zzz")])


def test_arithmetic():
    r = [rc(i, "treat", sid="t%d" % i) for i in range(20)] + \
        [rc(100 + i, "holdout", sid="h%d" % i) for i in range(20)]
    o = [oc("a", sid="t%d" % i, pid="p%d" % i) for i in range(15)] + \
        [oc("a", sid="h%d" % i, pid="p%d" % (100 + i)) for i in range(5)]
    rep = hl.report(r, o)
    assert not rep["insufficient"]
    assert rep["arms"]["treat"]["rate"] == 0.75 and rep["arms"]["holdout"]["rate"] == 0.25
    assert abs(rep["treat_minus_holdout_pp"] - 50.0) < 1e-9
    assert 0 < rep["p_value"] < 0.01


def test_insufficient():
    rep = hl.report([rc(1, "treat"), rc(2, "holdout")], [])
    assert rep["insufficient"] and rep["treat_minus_holdout_pp"] is None
    assert "n/a" in hl.format_report(rep)


def test_bad_lines_and_append(tmp_path):
    p = tmp_path / "o.jsonl"
    hl.append_outcome(str(p), "a", "s", "p1", "t1")
    with open(p, "a") as f:
        f.write("garbage\n[1]\n\n")
    rows, bad = hl.load(str(p))
    assert len(rows) == 1 and bad == 2


def test_cli_json(tmp_path):
    rp, op = tmp_path / "r.jsonl", tmp_path / "o.jsonl"
    rp.write_text(json.dumps(rc(1, "treat")) + "\nbad\n")
    hl.append_outcome(str(op), "a", "s", "p1", "t")
    out = subprocess.run([sys.executable, "-m", "backbone.hook_log", "report", "--json",
                          "--receipts", str(rp), "--outcomes", str(op)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    assert d["bad_lines"] == 1 and d["arms"]["treat"]["followed"] == 1 and d["insufficient"]
