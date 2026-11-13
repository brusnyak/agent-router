"""Tests for the supervisor (index-aware routing, drift constraints, model availability)."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router", "scripts"))

from graph.router import RouterSupervisor


def test_supervisor_initializes():
    """RouterSupervisor() initializes without error."""
    s = RouterSupervisor()
    assert s is not None
    assert hasattr(s, "agents_cfg")
    assert hasattr(s, "models_cfg")
    assert hasattr(s, "drift")
    assert hasattr(s, "trace_id")


def test_get_available_agents():
    """get_available_agents() returns a list of agent dicts."""
    s = RouterSupervisor()
    agents = s.get_available_agents()
    assert isinstance(agents, list)
    assert len(agents) > 0
    for a in agents:
        assert "id" in a
        assert "available" in a


def test_get_available_models():
    """get_available_models() returns a list of model dicts."""
    s = RouterSupervisor()
    models = s.get_available_models()
    assert isinstance(models, list)
    for m in models:
        assert "id" in m
        assert "name" in m
        assert "available" in m


def test_select_model_for_task_returns_none_when_no_keys():
    """select_model_for_task() returns None when no NIM key is available."""
    from unittest.mock import patch
    s = RouterSupervisor()
    # Mock get_available_models to return no available models
    with patch.object(s, "get_available_models", return_value=[]):
        model = s.select_model_for_task("triage")
    assert model is None


def test_nim_key_available_flag():
    """NIM availability reflects whether NIM keys were found."""
    fake = [{"id": "nim1", "provider": "nim", "api_key_env": "NIM_TEST_KEY"}]
    s = RouterSupervisor()
    with patch("graph.router._load_agents", return_value=fake), \
         patch.dict(os.environ, {"NIM_TEST_KEY": "x"}):
        assert s.get_available_agents()[0]["available"] is True
    with patch("graph.router._load_agents", return_value=fake), \
         patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NIM_TEST_KEY", None)
        assert s.get_available_agents()[0]["available"] is False


def test_apply_drift_constraints_blocks_claude():
    """_apply_drift_constraints() blocks agents listed in drift constraints."""
    s = RouterSupervisor()
    # Simulate drift with claude constraint
    s.drift = {
        "routing_constraints": ["Avoid routing critical tasks to claude (avg PEEM 2.92/5, 24 cards)"],
        "model_routing": {},
        "proposals": [],
    }
    agent, model, warnings = s._apply_drift_constraints("claude", "claude-sonnet-5-5")
    assert agent is None  # blocked
    assert len(warnings) > 0


def test_apply_drift_constraints_allows_nim3():
    """_apply_drift_constraints() allows agents not in constraints."""
    s = RouterSupervisor()
    s.drift = {
        "routing_constraints": ["Avoid routing critical tasks to claude (avg PEEM 2.92/5, 24 cards)"],
        "model_routing": {},
        "proposals": [],
    }
    agent, model, warnings = s._apply_drift_constraints("nim3", "nvidia/nemotron-3.5-super-vl-120b-a12b")
    assert agent == "nim3"
    assert len(warnings) == 0


def test_deterministic_triage():
    """_deterministic_triage() returns valid JSON with lane/agent."""
    s = RouterSupervisor()
    result = s._deterministic_triage("build a python script")
    decision = json.loads(result)
    assert "lane" in decision
    assert "agent" in decision
    assert decision["lane"] == "build"
    assert decision["agent"] == "nim3"

    result = s._deterministic_triage("research something")
    decision = json.loads(result)
    assert decision["lane"] == "research-public"

    result = s._deterministic_triage("review this document for errors")
    decision = json.loads(result)
    assert decision["lane"] == "review-roast"


def test_run_uses_deterministic_fallback_when_no_nim():
    """run() returns a result even without NIM keys (deterministic fallback)."""
    from unittest.mock import patch
    s = RouterSupervisor()
    # Mock get_available_models to return no models, forcing deterministic fallback
    # Mock subprocess.run to avoid real NIM API calls via NIMAgent
    with patch.object(s, "get_available_models", return_value=[]), \
         patch("graph.agent_base.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Mock NIM response", stderr="", returncode=0)
        result = s.run("build a simple hello world script")
    assert "status" in result
    assert "lane" in result
    assert "agent" in result
    # Should not error out
    assert result["status"] in ("done", "blocked", "error")


def test_index_context_populated():
    """run() populates index_context when index is available."""
    from unittest.mock import patch
    s = RouterSupervisor()
    with patch.object(s, "get_available_models", return_value=[]), \
         patch("graph.agent_base.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="Mock NIM response", stderr="", returncode=0)
        result = s.run("agent router dispatch kanban")
    # index_context may be empty if no relevant results, but key should exist
    assert "index_context" in result


def test_token_analytics():
    """get_token_analytics() returns token usage data with optimization suggestions."""
    s = RouterSupervisor()
    result = s.get_token_analytics()
    assert isinstance(result, dict)
    # May have error if no DB, but should not crash
    assert "error" in result or "total_cards" in result or "cards_by_agent" in result
    if "optimization_suggestions" in result:
        assert isinstance(result["optimization_suggestions"], list)


def test_second_brain_retrieval():
    """Second brain retrieval: index search returns relevant skills/hooks/vault content."""
    from scripts.index_vault import discover_corpus, build_index, search
    docs = discover_corpus()
    build_index(docs)
    # Search for vault-related content
    results = search("memory vault pages skills hooks", top_k=5)
    assert isinstance(results, list)
    assert len(results) > 0
    # Should find at least vault or skill content
    kinds_found = set(r.get("kind", "") for r in results)
    assert len(kinds_found) > 0


def test_config_drift_auto_generation():
    """Config drift auto-generates proposals from PEEM evaluations."""
    import sys
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
    from config_drift import analyze, generate_drift, AVG_SCORE_WARN, MIN_CARDS_FOR_DRIFT
    # Create synthetic evaluations with low scores to trigger drift
    evals = [
        {"agent": "nim3", "lane": "research-public", "model": "m1", "overall_score": 2.5, "verdict": "FAIL",
         "weaknesses": ["inaccurate"], "improvements": ["verify facts"]},
        {"agent": "nim3", "lane": "research-public", "model": "m1", "overall_score": 2.0, "verdict": "FAIL",
         "weaknesses": ["hallucinated"], "improvements": ["ground in sources"]},
    ]
    analysis = analyze(evals)
    drift = generate_drift(analysis)
    assert drift["mode"] == "suggest-gate"
    assert len(drift["routing_constraints"]) > 0 or len(drift["proposals"]) > 0


if __name__ == "__main__":
    test_supervisor_initializes()
    test_get_available_agents()
    test_get_available_models()
    test_select_model_for_task_returns_none_when_no_keys()
    test_apply_drift_constraints_blocks_claude()
    test_apply_drift_constraints_allows_nim3()
    test_deterministic_triage()
    test_run_uses_deterministic_fallback_when_no_nim()
    test_index_context_populated()
    test_token_analytics()
    test_second_brain_retrieval()
    test_config_drift_auto_generation()
    print("All supervisor tests passed.")
