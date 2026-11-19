#!/usr/bin/env python3
"""Self-configurator for agent-router.

Reads config/discovered-inventory.json (from discover_machine.py) and
generates/updates models.yaml, agents.yaml, skills.yaml, lanes.yaml.
Never installs anything — detects what is present, configures from it,
and prints a gaps report to stdout.

Idempotent: preserves manually-edited entries (marked _source: manual)
and only overwrites entries marked _source: discovered.
"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from backbone.catalog_ingest import ingest_all

ECC_DIR = os.path.expanduser("~/Developer/ecc-reference/agents")
AGENCY_DIR = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
from pathlib import Path
from typing import Any, Dict, List

import yaml

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
INVENTORY_PATH = os.path.join(CONFIG_DIR, "discovered-inventory.json")

VAULT_SANDBOX = os.path.join(HOME, "memory-vault", "agents")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)


def slugify(name: str) -> str:
    return name.lower().replace(" ", "-").replace("_", "-").replace("/", "-")


# ---------------------------------------------------------------------------
# models.yaml
# ---------------------------------------------------------------------------

KEY_MODEL_MAP = {
    "NIM_3": {"id": "nim-nemotron-3-5-super-vl", "name": "nvidia/nemotron-3.5-super-vl-120b-a12b", "provider": "nim", "role": "supervisor", "base_url": "https://integrate.api.nvidia.com/v1", "context_window": 128000},
    "NIM_2": {"id": "nim-nemotron-3-5-super-vl-2", "name": "nvidia/nemotron-3.5-super-vl-120b-a12b", "provider": "nim", "role": "worker", "base_url": "https://integrate.api.nvidia.com/v1", "context_window": 128000},
    "NIM_1": {"id": "nim-nemotron-3-5-super-vl-1", "name": "nvidia/nemotron-3.5-super-vl-120b-a12b", "provider": "nim", "role": "worker", "base_url": "https://integrate.api.nvidia.com/v1", "context_window": 128000},
    "NVIDIA_API_KEY_2": {"id": "nim-nemotron-3-ultra-550b", "name": "nvidia/nemotron-3-ultra-550b-a55b", "provider": "nim", "role": "worker", "base_url": "https://integrate.api.nvidia.com/v1", "context_window": 128000},
    "NVIDIA_API_KEY_1": {"id": "nim-nemotron-3-ultra-550b-1", "name": "nvidia/nemotron-3-ultra-550b-a55b", "provider": "nim", "role": "worker", "base_url": "https://integrate.api.nvidia.com/v1", "context_window": 128000},
    "ANTHROPIC_API_KEY": {"id": "claude-sonnet-5-5", "name": "claude-sonnet-5-5", "provider": "anthropic", "role": "worker", "context_window": 200000},
    "OPENAI_API_KEY": {"id": "gpt-6-1-sol", "name": "gpt-6.1-sol", "provider": "openai", "role": "worker", "context_window": 128000},
}


def build_models(env_file_has: Dict[str, bool]) -> List[dict]:
    models: List[dict] = []
    for key, info in KEY_MODEL_MAP.items():
        if env_file_has.get(key):
            entry = dict(info)
            entry["api_key_env"] = key
            entry["_source"] = "discovered"
            entry["_discovered_at"] = datetime.now(timezone.utc).isoformat()
            models.append(entry)
    return models


# ---------------------------------------------------------------------------
# agents.yaml
# ---------------------------------------------------------------------------

AGENT_DEFAULTS = {
    "claude": {"write_access": True, "route_reasons": ["browser", "mcp", "verify", "judgment", "private", "fresh-context"]},
    "codex": {"write_access": True, "route_reasons": ["build", "review"]},
    "opencode": {"write_access": True, "route_reasons": ["mechanical", "research-public", "content-clips"], "note": "owner uses by hand; do not spawn from sub-agents without explicit permission"},
    "cline": {"write_access": True, "route_reasons": ["build", "review"]},
    "kilo": {"write_access": True, "route_reasons": ["build", "review"], "note": "check if free tier available before routing"},
    "hermes": {"write_access": True, "route_reasons": ["hermes", "chat", "notification"]},
    "nim3": {"write_access": False, "route_reasons": ["supervisor", "research", "mechanical", "vision"]},
    "nim2": {"write_access": False, "route_reasons": ["hermes", "research"]},
    "nim1": {"write_access": False, "route_reasons": ["research"]},
}


def build_agents(cli_on_path: Dict[str, bool], config_dirs: Dict[str, Any], models: List[dict]) -> List[dict]:
    agents: Dict[str, dict] = {}
    # First: agents discovered from CLI + config
    for aid, found in cli_on_path.items():
        if not found:
            continue
        cfg = config_dirs.get(aid, {})
        if not cfg.get("exists"):
            continue
        defaults = AGENT_DEFAULTS.get(aid, {"write_access": False, "route_reasons": []})
        entry = {
            "id": aid,
            "cli": aid,
            "model": f"{aid}-default",
            "provider": aid,
            "write_access": defaults["write_access"],
            "route_reasons": defaults["route_reasons"],
            "skills": [],
            "interactive_mode": aid in ("claude", "codex", "opencode", "cline", "kilo", "hermes"),
            "_source": "discovered",
            "_discovered_at": datetime.now(timezone.utc).isoformat(),
        }
        if defaults.get("note"):
            entry["note"] = defaults["note"]
        if aid.startswith("nim"):
            entry["api_key_env"] = {"nim3": "NIM_3", "nim2": "NIM_2", "nim1": "NIM_1"}.get(aid, "NIM_3")
            entry["base_url"] = "https://integrate.api.nvidia.com/v1"
        agents[aid] = entry

    # Second: NIM agents from models.yaml (virtual agents, direct API, no CLI needed)
    key_to_id = {"NIM_3": "nim3", "NIM_2": "nim2", "NIM_1": "nim1",
                 "NVIDIA_API_KEY_2": "nim2", "NVIDIA_API_KEY_1": "nim1"}
    for m in models:
        if m.get("provider") != "nim":
            continue
        key_env = m.get("api_key_env", "")
        aid = key_to_id.get(key_env, f"nim-{slugify(key_env)}")
        if aid in agents:
            continue
        agents[aid] = {
            "id": aid,
            "cli": "nim_call.py",
            "model": m.get("name", ""),
            "provider": "nim",
            "api_key_env": key_env,
            "base_url": m.get("base_url", "https://integrate.api.nvidia.com/v1"),
            "write_access": False,
            "route_reasons": ["supervisor" if m.get("role") == "supervisor" else "research", "mechanical"],
            "skills": ["research-public", "mechanical"],
            "_source": "discovered",
            "_discovered_at": datetime.now(timezone.utc).isoformat(),
            "note": "Virtual NIM agent — direct API call, no CLI required",
        }
    return list(agents.values())


# ---------------------------------------------------------------------------
# skills.yaml
# ---------------------------------------------------------------------------

def build_skills(skills_locations: Dict[str, Any]) -> List[dict]:
    skills: List[dict] = []
    seen_ids = set()
    for loc, data in skills_locations.items():
        if not data.get("exists"):
            continue
        loc_path = Path(loc)
        home = Path(os.path.expanduser("~"))
        for sf in data.get("skill_files", []):
            sf_path = Path(sf)
            try:
                sf_display = "~" + str(sf_path)[len(str(home)):]
            except Exception:
                sf_display = str(sf_path)
            try:
                rel = sf_path.relative_to(loc_path)
            except ValueError:
                rel = sf_path.name
            sid = slugify(str(rel.with_suffix("")))
            if sid in seen_ids:
                continue
            seen_ids.add(sid)
            category = sf_path.parent.name
            skills.append({
                "id": sid,
                "path": sf_display,
                "category": category,
                "description": f"Auto-discovered skill from {sf_display}",
                "_source": "discovered",
                "_discovered_at": datetime.now(timezone.utc).isoformat(),
            })
    # Ingest ECC personas and agency agents as catalog skills
    ingested = ingest_all(ECC_DIR, AGENCY_DIR)
    home = Path(os.path.expanduser("~"))
    for s in ingested:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            sp = Path(s["path"])
            try:
                s["path"] = "~" + str(sp)[len(str(home)):]
                s["persona_file"] = "~" + str(Path(s["persona_file"]))[len(str(home)):]
            except Exception:
                pass
            s["_source"] = "discovered"
            s["_discovered_at"] = datetime.now(timezone.utc).isoformat()
            skills.append(s)

    return skills


# ---------------------------------------------------------------------------
# lanes.yaml
# ---------------------------------------------------------------------------

EXISTING_LANES = [
    {"id": "planner", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "does": "discuss, decide, write the packet, accept or reject results", "never": "execute lane work; read raw material over 200 lines", "skills": []},
    {"id": "build", "engine": "codex", "model": "gpt-6.1-sol", "effort": "medium", "skills": ["build-discipline", "karpathy-guidelines", "verification-before-completion"], "never": "execute without acceptance check"},
    {"id": "review-roast", "engine": "codex", "model": "gpt-6.1-sol", "effort": "medium", "skills": ["roast"]},
    {"id": "ops-repair", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": ["build-discipline", "verification-before-completion"], "never": "git push, rebase, reset, delete"},
    {"id": "config-edit", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": ["writing-skills"]},
    {"id": "research-public", "engine": "nim3", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "skills": ["search-first"], "data": "public only"},
    {"id": "mechanical", "engine": "nim3", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "skills": ["mechanical"]},
    {"id": "content-clips", "engine": "nim3", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "skills": ["content-clips"]},
    {"id": "vision", "engine": "nim3", "model": "nvidia/nemotron-3.5-super-vl-120b-a12b", "skills": ["vision"], "data": "public screenshots only"},
    {"id": "cash-leads", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": ["lead-dossier", "icp-qualification", "niche-scoring"], "never": "send"},
    {"id": "cash-outreach", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": ["offer-ladder"], "never": "send"},
    {"id": "upwork", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": ["upwork-scan"], "never": "submit, spend Connects"},
    {"id": "jobs", "engine": "claude", "model": "claude-sonnet-5-5", "effort": "medium", "skills": [], "never": "submit without exact-text yes"},
    {"id": "owner-only", "engine": "planner", "model": "claude-sonnet-5-5", "does": "approvals, deploys, sends, submits, spends — planner prepares, owner decides", "rule": "gate word overrides any lane"},
]


def build_lanes(existing_lanes_path: str, usable_agents: List[str]) -> List[dict]:
    existing = load_yaml(existing_lanes_path).get("lanes", [])
    lanes: List[dict] = []
    for ldef in existing:
        entry = dict(ldef)
        entry["_source"] = "discovered"
        entry["_discovered_at"] = datetime.now(timezone.utc).isoformat()
        engine = entry.get("engine", "")
        if engine not in usable_agents and engine not in ("script", "planner"):
            entry["fallback_needed"] = True
            entry["fallback_reason"] = f"CLI '{engine}' not found on PATH or config missing"
        entry["model_availability_check"] = True
        lanes.append(entry)
    return lanes


# ---------------------------------------------------------------------------
# Vault sandbox
# ---------------------------------------------------------------------------

def ensure_vault_sandbox() -> str:
    Path(VAULT_SANDBOX).mkdir(parents=True, exist_ok=True)
    return VAULT_SANDBOX


# ---------------------------------------------------------------------------
# Gaps report
# ---------------------------------------------------------------------------

def gaps_report(inventory: dict) -> List[str]:
    gaps: List[str] = []
    keys = inventory["keys"]
    agents = inventory["agents"]
    browsers = inventory["browsers"]

    if not any(keys["env_set"].values()):
        gaps.append("WARNING: No API keys in current environment. Keys found in ~/.env — use `with-env` or source ~/.env before running.")
    if keys["env_file_has"].get("NIM_1") and not keys["env_set"].get("NIM_1"):
        gaps.append("NIM_1 in ~/.env but not in current env")
    if keys["env_file_has"].get("NIM_2") and not keys["env_set"].get("NIM_2"):
        gaps.append("NIM_2 in ~/.env but not in current env")
    if keys["env_file_has"].get("NIM_3") and not keys["env_set"].get("NIM_3"):
        gaps.append("NIM_3 in ~/.env but not in current env")
    if keys["env_file_has"].get("ANTHROPIC_API_KEY") and not keys["env_set"].get("ANTHROPIC_API_KEY"):
        gaps.append("ANTHROPIC_API_KEY in ~/.env but not in current env")
    if keys["env_file_has"].get("OPENAI_API_KEY") and not keys["env_set"].get("OPENAI_API_KEY"):
        gaps.append("OPENAI_API_KEY in ~/.env but not in current env")
    if keys["env_file_has"].get("GEMINI_API_KEY") and not keys["env_set"].get("GEMINI_API_KEY"):
        gaps.append("GEMINI_API_KEY in ~/.env but not in current env")

    cli = agents["cli_on_path"]
    if not cli.get("opencode"):
        gaps.append("opencode CLI not on PATH — install or add to PATH for OpenCode routing")
    if cli.get("kilo") and not agents["config_dirs"].get("kilo", {}).get("exists"):
        gaps.append("kilo CLI found but no config dir — verify kilo is configured before routing")
    if cli.get("cline") and not agents["config_dirs"].get("cline", {}).get("exists"):
        gaps.append("cline CLI found but no config dir — verify cline is configured before routing")
    if cli.get("hermes") and not agents["config_dirs"].get("hermes", {}).get("exists"):
        gaps.append("hermes CLI found but no config dir — verify hermes is configured before routing")

    if not inventory["vault"]["exists"]:
        gaps.append("Vault not found at ~/memory-vault — vault-scoped features disabled until created")
    if not inventory["derived"]["vault_sandbox_ready"]:
        gaps.append("Vault agents sandbox missing — will be created at ~/memory-vault/agents/")

    running_browsers = [b for b in browsers if b["running"]]
    if not running_browsers:
        installed = [b for b in browsers if b["installed"]]
        if installed:
            names = ", ".join(b["display_name"] for b in installed)
            gaps.append(f"Browser(s) installed but not running: {names} — deep research via browser unavailable until started")
        else:
            gaps.append("No agentic browser (Neo/Ego) installed — browser-based deep research unavailable")

    return gaps


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Self-configurator for agent-router")
    ap.add_argument("--no-overwrite", action="store_true",
                    help="Preserve manually-edited config entries; only add new discovered entries")
    args = ap.parse_args()
    no_overwrite = args.no_overwrite

    if not Path(INVENTORY_PATH).exists():
        print(f"ERROR: {INVENTORY_PATH} not found. Run scripts/discover_machine.py first.")
        return 1

    with open(INVENTORY_PATH) as f:
        inventory = json.load(f)

    # Merge existing configs: keep manual entries, overwrite discovered.
    # If no_overwrite is True, manual entries are preserved and discovered
    # entries only added when no manual entry with the same key exists.
    def merge_list(root_key: str, new_entries: List[dict], key_field: str = "id",
                   no_overwrite: bool = False) -> dict:
        existing = load_yaml(os.path.join(CONFIG_DIR, f"{root_key}.yaml"))
        existing_list = existing.get(root_key, []) if isinstance(existing, dict) else []
        manual = {e[key_field]: e for e in existing_list if e.get("_source") != "discovered"}
        merged: Dict[str, dict] = {}
        # Start with manual entries (preserved)
        for e in manual.values():
            merged[e[key_field]] = e
        # Add discovered entries: skip if key already exists and no_overwrite
        for e in new_entries:
            key = e[key_field]
            if no_overwrite and key in merged:
                continue  # preserve existing manual entry
            merged[key] = e
        return {"version": 1, root_key: list(merged.values())}

    # models.yaml
    models_data = build_models(inventory["keys"]["env_file_has"])
    save_yaml(os.path.join(CONFIG_DIR, "models.yaml"), merge_list("models", models_data, no_overwrite=no_overwrite))

    # agents.yaml
    agents_data = build_agents(inventory["agents"]["cli_on_path"], inventory["agents"]["config_dirs"], models_data)
    save_yaml(os.path.join(CONFIG_DIR, "agents.yaml"), merge_list("agents", agents_data, no_overwrite=no_overwrite))

    # skills.yaml
    skills_data = build_skills(inventory["skills"])
    save_yaml(os.path.join(CONFIG_DIR, "skills.yaml"), merge_list("skills", skills_data, no_overwrite=no_overwrite))

    # lanes.yaml
    lanes_data = build_lanes(os.path.join(CONFIG_DIR, "lanes.yaml"), inventory["derived"]["usable_agents"])
    save_yaml(os.path.join(CONFIG_DIR, "lanes.yaml"), merge_list("lanes", lanes_data, no_overwrite=no_overwrite))

    # Vault sandbox
    sandbox = ensure_vault_sandbox()

    # Gaps report
    gaps = gaps_report(inventory)

    print("=== Configuration written ===")
    print(f"models.yaml: {len(models_data)} models")
    print(f"agents.yaml: {len(agents_data)} agents")
    print(f"skills.yaml: {len(skills_data)} skills")
    print(f"lanes.yaml: {len(lanes_data)} lanes")
    print(f"vault sandbox: {sandbox}")
    if gaps:
        print("\n=== Gaps (review before production use) ===")
        for g in gaps:
            print(f"  - {g}")
    else:
        print("\nNo gaps detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
