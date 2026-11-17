from backbone.retrieval import Registry

PROJECTS = """version: 1
projects:
  - id: alpha
    path: {base}
    keywords: [router, backbone]
    anchors:
      - a.md
  - id: beta
    path: {base}
    keywords: [plan, leads]
    anchors:
      - b.md
"""


def _registry(tmp_path):
    (tmp_path / "a.md").write_text("ALPHA ANCHOR\n")
    (tmp_path / "b.md").write_text("BETA ANCHOR\n")
    projects = tmp_path / "projects.yaml"
    projects.write_text(PROJECTS.format(base=tmp_path))
    return Registry(config_path=tmp_path / "retrieval.yaml", providers=[], projects_path=projects)


def test_auto_picks_project_by_keywords(tmp_path):
    reg = _registry(tmp_path)
    assert reg.resolve_project("what is the master plan for leads") == "beta"
    assert reg.resolve_project("fix the router backbone") == "alpha"
    assert reg.resolve_project("unrelated words only") == ""


def test_pack_auto_includes_the_matching_anchor_only(tmp_path):
    reg = _registry(tmp_path)
    pack = reg.context_pack("check the plan and leads", "auto")
    assert "BETA ANCHOR" in pack and "ALPHA ANCHOR" not in pack
    assert "ANCHOR" not in reg.context_pack("nothing relevant here", "auto")
