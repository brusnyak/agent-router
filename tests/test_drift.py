"""Tests for the config drift script."""
import json
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)

from scripts.config_drift import analyze, generate_drift, AVG_SCORE_WARN, AVG_SCORE_BLOCK, MIN_CARDS_FOR_DRIFT


def test_analyze_groups_by_agent():
    """analyze() groups evaluations by agent with avg scores."""
    evals = [
        {"agent": "nim3", "lane": "research", "model": "m1", "overall_score": 4.0, "verdict": "PASS",
         "weaknesses": [], "improvements": []},
        {"agent": "nim3", "lane": "research", "model": "m1", "overall_score": 4.5, "verdict": "PASS",
         "weaknesses": [], "improvements": []},
        {"agent": "codex", "lane": "build", "model": "m2", "overall_score": 2.0, "verdict": "FAIL",
         "weaknesses": ["slow"], "improvements": ["speed up"]},
    ]
    result = analyze(evals)
    assert result["total_evals"] == 3
    assert "nim3" in result["by_agent"]
    assert "codex" in result["by_agent"]
    assert result["by_agent"]["nim3"]["avg_score"] == 4.25
    assert result["by_agent"]["nim3"]["card_count"] == 2
    assert result["by_agent"]["codex"]["avg_score"] == 2.0
    assert result["by_agent"]["codex"]["fail_count"] == 1


def test_analyze_groups_by_lane():
    """analyze() groups evaluations by lane."""
    evals = [
        {"agent": "a1", "lane": "research-public", "model": "m1", "overall_score": 4.0, "verdict": "PASS",
         "weaknesses": [], "improvements": []},
        {"agent": "a2", "lane": "build", "model": "m2", "overall_score": 3.0, "verdict": "PASS_WITH_NOTES",
         "weaknesses": [], "improvements": []},
    ]
    result = analyze(evals)
    assert "research-public" in result["by_lane"]
    assert "build" in result["by_lane"]
    assert result["by_lane"]["research-public"]["avg_score"] == 4.0
    assert result["by_lane"]["build"]["avg_score"] == 3.0


def test_generate_drift_routing_constraints():
    """generate_drift() creates routing constraints for agents below block threshold."""
    analysis = {
        "total_evals": 4,
        "by_agent": {
            "claude": {"avg_score": 2.5, "card_count": 4, "fail_count": 4,
                       "top_weaknesses": ["inaccurate"], "top_improvements": ["verify"]},
            "nim3": {"avg_score": 4.2, "card_count": 4, "fail_count": 0,
                     "top_weaknesses": [], "top_improvements": []},
        },
        "by_lane": {
            "research-public": {"avg_score": 4.0, "card_count": 2},
            "build": {"avg_score": 3.0, "card_count": 2},
        },
        "by_model": {},
    }
    drift = generate_drift(analysis)
    assert drift["mode"] == "suggest-gate"
    assert len(drift["routing_constraints"]) > 0
    # claude at 2.5 < 3.0 should get a constraint
    claude_constraints = [c for c in drift["routing_constraints"] if "claude" in c]
    assert len(claude_constraints) > 0
    # nim3 at 4.2 should NOT get a constraint
    nim_constraints = [c for c in drift["routing_constraints"] if "nim3" in c]
    assert len(nim_constraints) == 0


def test_generate_drift_proposals():
    """generate_drift() creates proposals for agents below warn threshold."""
    analysis = {
        "total_evals": 4,
        "by_agent": {
            "codex": {"avg_score": 3.2, "card_count": 4, "fail_count": 0,
                      "top_weaknesses": ["verbose"], "top_improvements": ["be concise"]},
            "nim3": {"avg_score": 4.2, "card_count": 4, "fail_count": 0,
                     "top_weaknesses": [], "top_improvements": []},
        },
        "by_lane": {
            "build": {"avg_score": 3.2, "card_count": 4},
        },
        "by_model": {},
    }
    drift = generate_drift(analysis)
    # codex at 3.2 < 3.5 should get a proposal
    codex_proposals = [p for p in drift["proposals"] if "codex" in p.get("target", "")]
    assert len(codex_proposals) > 0
    assert codex_proposals[0]["status"] == "proposed"


def test_min_cards_threshold():
    """Agents with fewer than MIN_CARDS_FOR_DRIFT cards are skipped."""
    analysis = {
        "total_evals": 1,
        "by_agent": {
            "new-agent": {"avg_score": 1.0, "card_count": 1, "fail_count": 1,
                          "top_weaknesses": [], "top_improvements": []},
        },
        "by_lane": {},
        "by_model": {},
    }
    drift = generate_drift(analysis)
    # Should NOT generate constraints/proposals for new-agent (only 1 card < 2)
    assert len(drift["routing_constraints"]) == 0
    assert len(drift["proposals"]) == 0


def test_drift_yaml_structure():
    """Generated drift YAML has expected top-level keys."""
    analysis = {
        "total_evals": 2,
        "by_agent": {
            "test-agent": {"avg_score": 2.0, "card_count": 2, "fail_count": 2,
                           "top_weaknesses": ["x"], "top_improvements": ["y"]},
        },
        "by_lane": {},
        "by_model": {},
    }
    drift = generate_drift(analysis)
    assert "version" in drift
    assert "generated_at" in drift
    assert "source" in drift
    assert "mode" in drift
    assert drift["mode"] == "suggest-gate"
    assert "routing_constraints" in drift
    assert "proposals" in drift
    assert "summary" in drift


if __name__ == "__main__":
    test_analyze_groups_by_agent()
    test_analyze_groups_by_lane()
    test_generate_drift_routing_constraints()
    test_generate_drift_proposals()
    test_min_cards_threshold()
    test_drift_yaml_structure()
    print("All config drift tests passed.")
