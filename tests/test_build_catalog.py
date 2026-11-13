import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))
import build_catalog as bc  # noqa: E402


def _inv(tmp_path):
    s, a = tmp_path / "skills", tmp_path / "agents"
    (s / "foo").mkdir(parents=True)
    (s / "foo" / "SKILL.md").write_text('---\nname: "foo"\ndescription: \'does "x"\'\n---\nbody')
    a.mkdir()
    (a / "bar.md").write_text("---\nname: bar\ndescription: " + "z" * 500 + "\n---\n")
    (a / "dead.md").symlink_to(tmp_path / "missing.md")
    return s, a


def test_quotes_cap_and_symlink(tmp_path):
    s, a = _inv(tmp_path)
    items = bc.collect(s, a)
    assert items == [
        {"kind": "agent", "name": "bar", "desc": "z" * 300},
        {"kind": "skill", "name": "foo", "desc": 'does "x"'},
    ]


def test_deterministic_and_dryrun(tmp_path):
    s, a = _inv(tmp_path)
    out = tmp_path / "c.json"
    args = ["--skills-dir", str(s), "--agents-dir", str(a), "--out", str(out)]
    bc.main(args)
    assert not out.exists()
    bc.main(args + ["--write"])
    first = out.read_bytes()
    bc.main(args + ["--write"])
    assert out.read_bytes() == first
    assert json.loads(first)[0]["name"] == "bar"
