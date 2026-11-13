import json
from eval import librarian as L


def setup(tmp_path, cat, usage=(), labels=()):
    j = tmp_path / "judge"
    j.mkdir()
    (j / "catalog.json").write_text(json.dumps(cat))
    (j / "sonnet_a.jsonl").write_text("".join(json.dumps({"id": i, "label": l}) + "\n" for i, l in enumerate(labels)))
    pr = tmp_path / "home" / "projects" / "p"
    pr.mkdir(parents=True)
    with open(pr / "s.jsonl", "w") as f:
        for kind, n in usage:
            inp = {"skill": n} if kind == "Skill" else {"subagent_type": n}
            f.write(json.dumps({"message": {"content": [{"type": "tool_use", "name": kind, "input": inp}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"content": "SECRET PROMPT TEXT"}}) + "\n")
    out = tmp_path / "out"
    L.main(["--catalog", str(j / "catalog.json"), "--judge-dir", str(j),
            "--claude-home", str(tmp_path / "home"), "--out-dir", str(out)])
    return next(out.glob("librarian-*.md")).read_text()


def row(rep, name):
    return next(l for l in rep.splitlines() if "| %s |" % name in l)


def test_quote_normalization(tmp_path):
    rep = setup(tmp_path, [{"kind": "skill", "name": "'foo'", "desc": "alpha"}], usage=[("Skill", "foo")])
    assert "| foo | 1 |" in rep


def test_protected_pair_not_flagged(tmp_path):
    d = "web research sources citations summary"
    rep = setup(tmp_path, [{"kind": "skill", "name": "research", "desc": d},
                           {"kind": "agent", "name": "researcher", "desc": d}],
                usage=[("Skill", "research"), ("Agent", "researcher")])
    assert "MERGE" not in rep


def test_merge_when_similar(tmp_path):
    d = "pdf form filling extraction tool"
    rep = setup(tmp_path, [{"kind": "skill", "name": "a", "desc": d}, {"kind": "skill", "name": "b", "desc": d},
                           {"kind": "skill", "name": "c", "desc": "zebra"}],
                usage=[("Skill", "a"), ("Skill", "b")])
    assert "MERGE(b)" in row(rep, "a")


def test_retire(tmp_path):
    rep = setup(tmp_path, [{"kind": "skill", "name": "dead", "desc": "x"}])
    assert "RETIRE" in row(rep, "dead")


def test_activation_gap(tmp_path):
    rep = setup(tmp_path, [{"kind": "skill", "name": "hot", "desc": "x"}], labels=["hot"] * 8 + ["none"])
    r = row(rep, "hot")
    assert "KEEP" in r and "activation-gap" in r and "| 8 |" in r


def test_no_prompt_text(tmp_path):
    rep = setup(tmp_path, [{"kind": "skill", "name": "foo", "desc": "x"}], usage=[("Skill", "foo")])
    assert "SECRET" not in rep
