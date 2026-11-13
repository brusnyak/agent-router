import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval import shadow_enrich as se  # noqa: E402

PROMPT = "SECRET-PROMPT-TEXT please do the thing"


def setup(tmp_path, with_prompt=True):
    proj = tmp_path / "projects" / "p"
    proj.mkdir(parents=True)
    lines = [{"type": "user", "message": {"role": "user", "content": PROMPT + "\n"}}] if with_prompt else []
    (proj / "s1.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    rec = tmp_path / "r.jsonl"
    rows = [{"receipt_id": "a", "mode": "shadow", "would_surface": [], "session_id": "s1", "prompt_hash": se.sha(PROMPT)},
            {"receipt_id": "b", "mode": "live", "would_surface": [], "session_id": "s1", "prompt_hash": "x"}]
    rec.write_text("".join(json.dumps(x) + "\n" for x in rows))
    return str(tmp_path / "projects"), rec, tmp_path / "o.jsonl"


def run(proj, rec, out, ret, T=0.0):
    _, rows = se.enrich(rec, out, ret, projects=proj, T=T)
    with open(out, "a") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    return rows


def test_hash_lookup_and_surface(tmp_path):
    proj, rec, out = setup(tmp_path)
    rows = run(proj, rec, out, lambda q: [("x", .9), ("y", .5), ("z", .1)])
    assert len(rows) == 1 and rows[0]["would_surface"] == ["x", "y", "z"] and rows[0]["margin"] == 0.4


def test_missing_prompt(tmp_path):
    proj, rec, out = setup(tmp_path, with_prompt=False)
    rows = run(proj, rec, out, lambda q: [("x", 1), ("y", 0)])
    assert rows[0]["abstention"] == "prompt-not-found" and rows[0]["would_surface"] == []


def test_idempotent_and_input_unchanged(tmp_path):
    proj, rec, out = setup(tmp_path)
    before = rec.read_bytes()
    ret = lambda q: [("x", .9), ("y", .5)]
    run(proj, rec, out, ret)
    assert run(proj, rec, out, ret) == []
    assert len(out.read_text().splitlines()) == 1 and rec.read_bytes() == before


def test_margin_gate_abstains(tmp_path):
    proj, rec, out = setup(tmp_path)
    rows = run(proj, rec, out, lambda q: [("x", .6), ("y", .55)], T=0.2)
    assert rows[0]["would_surface"] == [] and rows[0]["abstention"] == "margin"


def test_no_prompt_text_in_output(tmp_path):
    proj, rec, out = setup(tmp_path)
    run(proj, rec, out, lambda q: [("x", .9), ("y", .5)])
    assert "SECRET-PROMPT-TEXT" not in out.read_text()
