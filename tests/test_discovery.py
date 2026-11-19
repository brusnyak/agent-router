"""Tests for machine discovery script."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.discover_machine import discover, scan_cli_on_path, scan_agent_configs, scan_env_keys, scan_browsers, scan_vault, scan_skills, scan_hooks


def test_discover_returns_inventory():
    """discover() returns a dict with expected top-level keys."""
    inv = discover()
    assert "version" in inv
    assert "machine" in inv
    assert "agents" in inv
    assert "keys" in inv
    assert "browsers" in inv
    assert "vault" in inv
    assert "skills" in inv
    assert "hooks" in inv
    assert "project_roots" in inv
    assert "last30days" in inv
    assert "derived" in inv


def test_discover_writes_inventory_file():
    """discover() + main() writes config/discovered-inventory.json."""
    from scripts.discover_machine import main
    INVENTORY_PATH = os.path.join(PROJECT_ROOT, "config", "discovered-inventory.json")
    # Remove existing to test fresh write
    if os.path.exists(INVENTORY_PATH):
        os.remove(INVENTORY_PATH)
    main()
    assert os.path.exists(INVENTORY_PATH)
    with open(INVENTORY_PATH) as f:
        inv = json.load(f)
    assert "derived" in inv
    assert "usable_agents" in inv["derived"]


def test_scan_cli_on_path_returns_dict():
    """scan_cli_on_path() returns a dict with agent IDs as keys."""
    result = scan_cli_on_path()
    assert isinstance(result, dict)
    for aid in ("claude", "codex", "opencode", "cline", "kilo", "hermes"):
        assert aid in result
        assert isinstance(result[aid], bool)


def test_scan_agent_configs_returns_dict():
    """scan_agent_configs() returns config info per agent."""
    result = scan_agent_configs()
    assert isinstance(result, dict)
    for aid in ("claude", "codex"):
        assert aid in result
        assert "exists" in result[aid]
        assert "config_home" in result[aid]


def test_scan_env_keys_returns_dict():
    """scan_env_keys() returns dict of key presence."""
    result = scan_env_keys()
    assert isinstance(result, dict)
    for k in ("NIM_1", "NIM_2", "NIM_3", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert k in result
        assert isinstance(result[k], bool)


def test_scan_browsers_returns_list():
    """scan_browsers() returns a list of browser dicts."""
    result = scan_browsers()
    assert isinstance(result, list)
    for b in result:
        assert "id" in b
        assert "display_name" in b
        assert "installed" in b
        assert "running" in b
        assert "launch_cmd" in b


def test_scan_vault_returns_dict():
    """scan_vault() returns vault info dict."""
    result = scan_vault()
    assert isinstance(result, dict)
    assert "path" in result
    assert "exists" in result
    assert "agents_sandbox" in result


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/.claude/skills")), reason="machine-local skills corpus absent")
def test_scan_skills_returns_dict():
    """scan_skills() returns dict keyed by location."""
    result = scan_skills()
    assert isinstance(result, dict)
    total = 0
    for loc, data in result.items():
        assert "exists" in data
        assert "skill_files" in data
        total += len(data.get("skill_files", []))
    assert total > 0  # We know there are skills on this machine


def test_scan_hooks_returns_dict():
    """scan_hooks() returns hook info dict."""
    result = scan_hooks()
    assert isinstance(result, dict)
    assert "path" in result
    assert "exists" in result
    assert "hook_files" in result


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/.claude")), reason="no claude config dir on this machine")
def test_derived_usable_agents():
    """derived.usable_agents contains agents with CLI + config."""
    inv = discover()
    usable = inv["derived"]["usable_agents"]
    assert isinstance(usable, list)
    # claude and codex are known to be installed + configured
    assert "claude" in usable
    assert "codex" in usable


def test_browsers_available():
    """derived.browsers_available is a list; its contents are machine-specific."""
    inv = discover()
    browsers = inv["derived"]["browsers_available"]
    assert isinstance(browsers, list)
    assert all(isinstance(b, str) for b in browsers)


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/memory-vault")), reason="machine-local vault absent")
def test_vault_sandbox_ready():
    """derived.vault_sandbox_ready is True when vault exists."""
    inv = discover()
    assert inv["derived"]["vault_sandbox_ready"] is True


if __name__ == "__main__":
    test_discover_returns_inventory()
    test_discover_writes_inventory_file()
    test_scan_cli_on_path_returns_dict()
    test_scan_agent_configs_returns_dict()
    test_scan_env_keys_returns_dict()
    test_scan_browsers_returns_list()
    test_scan_vault_returns_dict()
    test_scan_skills_returns_dict()
    test_scan_hooks_returns_dict()
    test_derived_usable_agents()
    test_browsers_available()
    test_vault_sandbox_ready()
    print("All discovery tests passed.")


def test_key_discovery_is_provider_agnostic_and_names_only(tmp_path):
    from backbone import keys
    env = tmp_path / "env"
    env.write_text("export GROQ_API_KEY=SENTINEL-1\nNIM_1=SENTINEL-2\nNIM_2=x\nACMEAI_API_KEY=SENTINEL-3\nKAGGLE_API_TOKEN=SENTINEL-4\nPATH_THING=1\n# TOKEN=no\n")
    known = {"groq": {"base_url": "https://g/v1"}, "nim": {"base_url": "https://n/v1", "aliases": ["nvidia"]}}
    got = keys.discover_keys(paths=[str(env)], environ={}, known=known)
    assert got["groq"] == {"keys": ["GROQ_API_KEY"], "llm": True, "base_url": "https://g/v1"}
    assert got["nim"]["keys"] == ["NIM_1", "NIM_2"] and got["nim"]["llm"]
    assert got["acmeai"]["llm"] is False and got["kaggle"]["keys"] == ["KAGGLE_API_TOKEN"]   # unknown providers still listed
    assert "SENTINEL" not in repr(got) and "path" not in got                                   # never values; non-key names ignored


def test_discover_feeds_init_config_for_any_provider(tmp_path):
    from backbone import discover as bd
    env = tmp_path / "env"
    env.write_text("OPENROUTER_API_KEY=x\nGROQ_API_KEY=y\nNIM_1=z\n")
    caps = bd.discover(env={}, which=lambda b: None, ssh_config=str(tmp_path / "none"), project_roots=[], env_files=[str(env)])
    assert set(caps["keys"]) == {"openrouter", "groq", "nim"}
    cfg = bd.init_config(caps, {"nim": {}, "workers": {}})
    assert cfg["nim"]["keys"] == ["NIM_1"] and cfg["providers"]["groq"]["keys"] == ["GROQ_API_KEY"]
    assert cfg["providers"]["openrouter"]["base_url"].startswith("https://")
