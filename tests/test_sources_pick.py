"""Source self-discovery and the skill picker. Discovery tests use a temp HOME; the eval test uses the live index if present."""
import json
import os

import pytest

from backbone import pick as P
from backbone import sources as S


def mk(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_discover_finds_roots_by_shape_and_skips_junk(tmp_path):
    for n in ("alpha", "beta"):
        mk(tmp_path / "tools/skills" / n / "SKILL.md")
    for i in range(6):                                   # persona repo: frontmatter name+description, no agents/ dir name
        mk(tmp_path / f"vendor/personas/p{i}.md", f"---\nname: P{i}\ndescription: does {i}\n---\nbody")
    mk(tmp_path / "x/commands/deploy.md")
    mk(tmp_path / "docs/ja-JP/skills/alpha/SKILL.md")      # translation
    mk(tmp_path / ".codex/quarantine-2026/plug/skills/q/SKILL.md")
    mk(tmp_path / "node_modules/m/skills/z/SKILL.md")
    found = {(f["kind"], os.path.relpath(os.path.expanduser(f["path"].replace("~", str(tmp_path), 1)), tmp_path)) for f in S.discover(str(tmp_path))}
    assert found == {("skill", "tools/skills"), ("agent", "vendor/personas"), ("command", "x/commands")}


def test_only_unique_drops_mirrors(tmp_path):
    mk(tmp_path / "a/skills/one/SKILL.md"); mk(tmp_path / "b/skills/one/SKILL.md"); mk(tmp_path / "b/skills/two/SKILL.md")
    found = [{"path": str(tmp_path / "a/skills"), "kind": "skill", "files": 1}, {"path": str(tmp_path / "b/skills"), "kind": "skill", "files": 2}]
    out = S.only_unique(found, known=set())
    assert [(o["path"].endswith("b/skills"), o["unique"]) for o in out] == [(True, 2)]    # b first (bigger); a adds nothing new


IDX = [
    {"kind": "skill", "name": "database-migrations", "description": "Safe schema migrations, add column, backfill, rollback."},
    {"kind": "skill", "name": "kubernetes-patterns", "description": "Kubernetes deployment manifests, helm charts, probes."},
    {"kind": "agent", "name": "kubernetes-specialist", "description": "Kubernetes cluster specialist, manifests and helm."},
    {"kind": "skill", "name": "make-interfaces-feel-better", "description": "Polish UI details so interfaces feel better."},
    {"kind": "command", "name": "go-test", "description": "Run go tests with coverage."},
] + [{"kind": "skill", "name": f"filler-{i}", "description": f"unrelated topic number {i} about gardening"} for i in range(30)]


def test_pick_relevant_abstains_on_chatter_and_followups(monkeypatch):
    monkeypatch.setattr(P, "FLOOR", 1.0)
    got = P.pick(IDX, "write a database migration that adds a column and backfills it")
    assert got and got[0]["name"] == "database-migrations"
    assert P.pick(IDX, "which one is better") is None                    # generic word in a name is not enough
    assert P.pick(IDX, "no, the database migrations are fine") is None   # follow-up reply
    assert P.pick(IDX, "thanks") is None


def test_pick_prefers_skill_over_same_topic_agent(monkeypatch):
    monkeypatch.setattr(P, "FLOOR", 1.0)
    got = P.pick(IDX, "set up kubernetes deployment manifests and a helm chart")
    assert got and got[0]["kind"] == "skill"


def test_body_is_not_searched():
    idx = [{"kind": "skill", "name": "alpha-tool", "description": "does alpha", "body": "kubernetes helm manifests " * 50}] + IDX
    assert (P.pick(idx, "kubernetes helm manifests") or [{}])[0].get("name") != "alpha-tool"


LIVE = os.path.expanduser("~/.agent-router/library-index.jsonl")


@pytest.mark.skipif(not os.path.exists(LIVE), reason="no live library index on this machine")
def test_live_index_meets_selection_thresholds():
    idx = [json.loads(l) for l in open(LIVE) if l.strip()]
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "skill_select.json")))
    r = P.evaluate(idx, fx)
    assert r["p_at_1"] >= 0.80 and r["fp_rate"] <= 0.05 and r["wrong_rate"] <= 0.05, r
