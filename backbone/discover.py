"""Detect what this machine has: agent CLIs, provider keys (names only), ssh hosts, git projects.
Nothing here is specific to one owner; `backbone init` turns the result into a config."""
from __future__ import annotations

import os
import re
import shutil
from typing import Callable, Dict, List, Optional

AGENT_BINS = ["claude", "codex", "opencode", "omp", "qwen", "kilo", "pi", "cline", "hermes", "goose", "crush"]


def ssh_hosts(path: str = "~/.ssh/config") -> List[str]:
    try:
        text = open(os.path.expanduser(path)).read()
    except OSError:
        return []
    out: List[str] = []
    for m in re.finditer(r"(?mi)^\s*Host\s+(.+)$", text):
        out += [h for h in m.group(1).split() if not re.search(r"[*?!]", h)]
    return out


def git_projects(roots: Optional[List[str]] = None, limit: int = 30) -> List[str]:
    found: List[str] = []
    for root in roots or ["~/Developer", "~/Projects", "~/code", "~/src"]:
        r = os.path.expanduser(root)
        if not os.path.isdir(r):
            continue
        for d in sorted(os.listdir(r)):
            p = os.path.join(r, d)
            if os.path.isdir(os.path.join(p, ".git")):
                found.append(p)
    return found[:limit]


def discover(env: Optional[dict] = None, which: Callable[[str], Optional[str]] = shutil.which,
             ssh_config: str = "~/.ssh/config", project_roots: Optional[List[str]] = None,
             env_files=None) -> Dict:
    from .keys import ENV_FILES
    # an explicit env means "use only this" (hermetic); the real run (env=None) also reads key NAMES from the env files
    env_files = (ENV_FILES if env is None else ()) if env_files is None else env_files
    from . import keys as _keys
    from .harness import ROOT, load_yaml
    try:
        known = load_yaml(ROOT / "config/providers.yaml").get("providers", {})
    except (OSError, ValueError):
        known = {}
    # any provider, from key NAMES in env files + environment (values are never read); only LLM providers feed init_config
    found = _keys.discover_keys(env_files, env, known)
    keys: Dict[str, List[str]] = {p: v["keys"] for p, v in found.items() if v["llm"]}
    other = {p: v["keys"] for p, v in found.items() if not v["llm"]}
    return {"other_secrets": other, "providers": {p: found[p]["base_url"] for p in keys}, "agents": {a: which(a) for a in AGENT_BINS if which(a)}, "keys": keys,
            "ssh_hosts": ssh_hosts(ssh_config), "projects": git_projects(project_roots)}


def init_config(caps: Dict, base: Dict) -> Dict:
    """Derive a config from capabilities: only workers that exist, only keys that are present.

    Never falls back to sample key names or keeps workers (e.g. pi) that were not found.
    Missing keys means an empty list and no default_key; the operator must supply real keys.
    """
    cfg = {**base}
    nim_keys = list(caps["keys"].get("nim") or [])
    cfg["nim"] = {**base["nim"], "keys": nim_keys}
    cfg["nim"]["default_key"] = nim_keys[0] if nim_keys else ""
    cfg["workers"] = {k: v for k, v in base["workers"].items() if k in caps["agents"]}
    expert = next((a for a in ("codex", "claude") if a in caps["agents"]), "")
    cfg["escalation"] = {"expert": expert}
    # every other discovered LLM provider: keys + endpoint, so a worker/model entry can name them (operator picks the model)
    cfg["providers"] = {p: {"keys": names, "base_url": (caps.get("providers") or {}).get(p, "")}
                        for p, names in caps["keys"].items() if p != "nim"}
    cfg["hosts"] = base.get("hosts", {})
    return cfg
