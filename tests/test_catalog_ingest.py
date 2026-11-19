"""Tests for catalog ingestion of ECC personas and agency agents (Horizon 2B)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backbone.catalog_ingest import ingest_all, ingest_ecc_agents, ingest_agency_agents, slugify


def test_slugify():
    assert slugify("My Skill Name") == "my-skill-name"
    assert slugify("UI Designer") == "ui-designer"


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/Developer/ecc-reference/agents")), reason="machine-local ecc corpus absent")
def test_ingest_ecc_agents():
    ecc_dir = os.path.expanduser("~/Developer/ecc-reference/agents")
    skills = ingest_ecc_agents(ecc_dir)
    assert len(skills) == 71
    ids = {s["id"] for s in skills}
    assert "ecc-architect" in ids
    assert "ecc-code-reviewer" in ids
    for s in skills:
        assert s["category"] == "ecc-persona"
        assert s["_source"] == "ecc-reference"
        assert "persona_file" in s
        assert s["id"].startswith("ecc-")


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")), reason="machine-local agency corpus absent")
def test_ingest_agency_agents():
    agency_dir = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
    skills = ingest_agency_agents(agency_dir)
    assert len(skills) > 200
    ids = {s["id"] for s in skills}
    assert "agency-design-ui-designer" in ids
    for s in skills:
        assert s["category"].startswith("agency-")
        assert s["_source"] == "agency-agents"
        assert "persona_file" in s
        assert s["id"].startswith("agency-")


@pytest.mark.skipif(
    not (os.path.isdir(os.path.expanduser("~/Developer/ecc-reference/agents"))
         and os.path.isdir(os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents"))),
    reason="machine-local corpora absent")
def test_ingest_all_dedupes_by_id():
    ecc_dir = os.path.expanduser("~/Developer/ecc-reference/agents")
    agency_dir = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
    skills = ingest_all(ecc_dir, agency_dir)
    ids = [s["id"] for s in skills]
    assert len(ids) == len(set(ids)), "duplicate ids found"
    assert len(skills) == 71 + 307


def test_skill_has_required_fields():
    ecc_dir = os.path.expanduser("~/Developer/ecc-reference/agents")
    agency_dir = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
    skills = ingest_all(ecc_dir, agency_dir)
    required = ["id", "path", "category", "description", "persona_file", "_source"]
    for s in skills:
        for k in required:
            assert k in s, f"missing {k} in {s.get('id')}"
        assert s["description"], f"empty description in {s['id']}"


if __name__ == "__main__":
    test_slugify()
    test_ingest_ecc_agents()
    test_ingest_agency_agents()
    test_ingest_all_dedupes_by_id()
    test_skill_has_required_fields()
    print("All catalog ingestion tests passed.")
