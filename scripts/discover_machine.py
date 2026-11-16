#!/usr/bin/env python3
"""Machine discovery for agent-router.

Scans the local machine and emits a JSON inventory used to self-configure
models.yaml, agents.yaml, skills.yaml, lanes.yaml on first run. Never installs
anything — only detects what is present and suggests setup gaps.

Output: config/discovered-inventory.json (inside the agent-router project).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
OUTPUT_PATH = os.path.join(CONFIG_DIR, "discovered-inventory.json")

# ---------------------------------------------------------------------------
# 1. CLI agent scan (PATH + config dirs)
# ---------------------------------------------------------------------------

KNOWN_CLI_AGENTS = [
    {"id": "claude", "cli": "claude", "config_home": os.path.join(HOME, ".claude")},
    {"id": "codex", "cli": "codex", "config_home": os.path.join(HOME, ".codex")},
    {"id": "opencode", "cli": "opencode", "config_home": os.path.join(HOME, ".config", "opencode")},
    {"id": "cline", "cli": "cline", "config_home": os.path.join(HOME, ".vscode", "cline")},
    {"id": "kilo", "cli": "kilo", "config_home": os.path.join(HOME, ".kilo")},
    {"id": "hermes", "cli": "hermes", "config_home": os.path.join(HOME, ".hermes")},
]


def scan_cli_on_path() -> Dict[str, bool]:
    return {e["id"]: shutil.which(e["cli"]) is not None for e in KNOWN_CLI_AGENTS}


def scan_agent_configs() -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for entry in KNOWN_CLI_AGENTS:
        ch = entry["config_home"]
        found: Dict[str, List[str]] = {}
        if os.path.isdir(ch):
            for pattern in ("config.toml", "config.json", "settings.json", "AGENTS.md", "CLAUDE.md", "skills.yaml", "agents.yaml"):
                matches = glob.glob(os.path.join(ch, "**", pattern), recursive=True)
                if matches:
                    found[pattern] = matches[:3]
        result[entry["id"]] = {
            "config_home": ch,
            "exists": os.path.isdir(ch),
            "configs": found,
        }
    return result


# ---------------------------------------------------------------------------
# 2. API key / env scan
# ---------------------------------------------------------------------------

KNOWN_KEYS = ["NIM_1", "NIM_2", "NIM_3", "NVIDIA_API_KEY_1", "NVIDIA_API_KEY_2",
              "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"]


def scan_env_keys() -> Dict[str, bool]:
    return {k: bool(os.environ.get(k)) for k in KNOWN_KEYS}


def scan_env_file_keys() -> Dict[str, bool]:
    """Check ~/.env and project .env for key names (values never read)."""
    found: Dict[str, bool] = {}
    for envfile in (os.path.join(HOME, ".env"), os.path.join(PROJECT_ROOT, ".env")):
        if os.path.isfile(envfile):
            try:
                text = Path(envfile).read_text(errors="ignore")
                for k in KNOWN_KEYS:
                    if k in text:
                        found[k] = True
            except OSError:
                pass
    return found


# ---------------------------------------------------------------------------
# 3. Browser detection (Neo / Ego)
# ---------------------------------------------------------------------------

KNOWN_BROWSERS = [
    {"id": "browserclaw", "name": "BrowserClaw", "bundle": "com.browseros.BrowserClaw", "aliases": ["neo", "browseros neo"]},
    {"id": "ego-lite", "name": "ego lite", "bundle": "com.citrolabs.ego.lite", "aliases": ["ego", "ego lite"]},
]


def _mdls(bundle_id: str) -> Optional[str]:
    try:
        out = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def _running(process_name: str) -> bool:
    try:
        out = subprocess.run(["pgrep", "-ax", process_name],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return bool(out)
    except Exception:
        return False


def scan_browsers() -> List[Dict[str, Any]]:
    browsers: List[Dict[str, Any]] = []
    for b in KNOWN_BROWSERS:
        app_path = _mdls(b["bundle"])
        running = _running(b["name"])
        browsers.append({
            "id": b["id"],
            "display_name": b["name"],
            "bundle_id": b["bundle"],
            "aliases": b["aliases"],
            "app_path": app_path,
            "installed": app_path is not None,
            "running": running,
            "launch_cmd": f'open -a "{b["name"]}"',
        })
    return browsers


# ---------------------------------------------------------------------------
# 4. Vault, skills, hooks, projects
# ---------------------------------------------------------------------------

def _exists(path: str) -> bool:
    return os.path.exists(path)


def scan_vault() -> Dict[str, Any]:
    vault = os.path.join(HOME, "memory-vault")
    return {
        "path": vault,
        "exists": _exists(vault),
        "claude_md": _exists(os.path.join(vault, "CLAUDE.md")),
        "pages_dir": _exists(os.path.join(vault, "pages")),
        "scripts_dir": _exists(os.path.join(vault, "scripts")),
        "kanban_db": _exists(os.path.join(vault, "kanban.db")),
        "agents_sandbox": os.path.join(vault, "agents"),
        "agents_sandbox_exists": _exists(os.path.join(vault, "agents")),
    }


def scan_skills() -> Dict[str, Any]:
    locations = [
        os.path.join(HOME, ".agent-skills"),
        os.path.join(HOME, ".claude", "skills"),
        os.path.join(PROJECT_ROOT, "config"),
        os.path.join(HOME, "Developer", "ecc-reference", "skills"),
    ]
    found: Dict[str, Any] = {}
    for loc in locations:
        skill_files: List[str] = []
        if os.path.isdir(loc):
            skill_files = glob.glob(os.path.join(loc, "**", "SKILL.md"), recursive=True)[:50]
        found[loc] = {"exists": os.path.isdir(loc), "skill_files": skill_files}
    return found


def scan_ecc_agents() -> Dict[str, Any]:
    ecc_agents_dir = os.path.join(HOME, "Developer", "ecc-reference", "agents")
    found: Dict[str, Any] = {"exists": os.path.isdir(ecc_agents_dir), "agents": []}
    if os.path.isdir(ecc_agents_dir):
        for p in sorted(glob.glob(os.path.join(ecc_agents_dir, "*.md"))):
            found["agents"].append(os.path.basename(p))
    return found


def scan_agency_agents() -> Dict[str, Any]:
    agency_dir = os.path.join(HOME, ".agent-skills", "vendor", "msitarzewski_agency-agents")
    found: Dict[str, Any] = {"exists": os.path.isdir(agency_dir), "agents": []}
    if os.path.isdir(agency_dir):
        for p in sorted(glob.glob(os.path.join(agency_dir, "**", "*.md"), recursive=True)):
            rel = os.path.relpath(p, agency_dir)
            if rel.split(os.sep)[0] in ("examples", "integrations", "scripts", ".github", "i18n"):
                continue
            if os.path.basename(p).upper().startswith(("README", "CONTRIBUTING")):
                continue
            found["agents"].append(rel)
    return found


def scan_hooks() -> Dict[str, Any]:
    hooks_dir = os.path.join(HOME, ".claude", "hooks")
    hook_files: List[str] = []
    if os.path.isdir(hooks_dir):
        hook_files = glob.glob(os.path.join(hooks_dir, "*.py"))
    return {
        "path": hooks_dir,
        "exists": os.path.isdir(hooks_dir),
        "hook_files": hook_files,
    }


def scan_project_roots() -> Dict[str, Any]:
    roots = [
        os.path.join(HOME, "Developer"),
        os.path.join(HOME, "Documents", "Acore"),
        os.path.join(HOME, "memory-vault"),
    ]
    found: Dict[str, Any] = {}
    for r in roots:
        subdirs: List[str] = []
        if os.path.isdir(r):
            try:
                subdirs = [d for d in os.listdir(r)
                           if os.path.isdir(os.path.join(r, d))][:20]
            except OSError:
                pass
        found[r] = {"exists": os.path.isdir(r), "subdirs": subdirs}
    return found


# ---------------------------------------------------------------------------
# 5. last30days output
# ---------------------------------------------------------------------------

def scan_last30days() -> Dict[str, Any]:
    paths = [
        os.path.join(HOME, "Developer", "refs", "mvanhorn_last30days-skill"),
        os.path.join(HOME, "memory-vault", "pages"),
    ]
    found: Dict[str, Any] = {}
    for p in paths:
        found[p] = {"exists": os.path.isdir(p)}
    return found


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def discover() -> Dict[str, Any]:
    inventory = {
        "version": 1,
        "discovered_at": __import__("datetime").datetime.now().isoformat(),
        "machine": {
            "home": HOME,
            "platform": sys.platform,
        },
        "agents": {
            "cli_on_path": scan_cli_on_path(),
            "config_dirs": scan_agent_configs(),
        },
        "keys": {
            "env_set": scan_env_keys(),
            "env_file_has": scan_env_file_keys(),
        },
        "browsers": scan_browsers(),
        "vault": scan_vault(),
        "skills": scan_skills(),
        "ecc_agents": scan_ecc_agents(),
        "agency_agents": scan_agency_agents(),
        "hooks": scan_hooks(),
        "project_roots": scan_project_roots(),
        "last30days": scan_last30days(),
    }

    # Derived: which agents are fully usable (CLI found + config exists, or NIM keys present)
    usable_agents: List[str] = []
    cli_found = inventory["agents"]["cli_on_path"]
    config_dirs = inventory["agents"]["config_dirs"]
    keys_env = inventory["keys"]["env_set"]
    keys_file = inventory["keys"]["env_file_has"]
    for aid, found in cli_found.items():
        if found and config_dirs.get(aid, {}).get("exists"):
            usable_agents.append(aid)
    # NIM agents are usable if their key exists in env or ~/.env
    for aid, key_env in (("nim3", "NIM_3"), ("nim2", "NIM_2"), ("nim1", "NIM_1")):
        if keys_env.get(key_env) or keys_file.get(key_env):
            usable_agents.append(aid)
    # NIM key is available if in os.environ OR in either env file (~/.env or project .env)
    keys_all = {**inventory["keys"]["env_set"], **inventory["keys"]["env_file_has"]}
    inventory["derived"] = {
        "usable_agents": usable_agents,
        "any_nim_key": any(keys_all.get(k, False) for k in ("NIM_1", "NIM_2", "NIM_3")),
        "any_claude_key": keys_all.get("ANTHROPIC_API_KEY", False),
        "any_openai_key": keys_all.get("OPENAI_API_KEY", False),
        "browsers_available": [b["id"] for b in inventory["browsers"] if b["installed"]],
        "vault_sandbox_ready": inventory["vault"]["exists"],
    }
    return inventory


def main() -> int:
    inventory = discover()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    Path(OUTPUT_PATH).write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(inventory["derived"], indent=2))
    print(f"\nFull inventory written to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
