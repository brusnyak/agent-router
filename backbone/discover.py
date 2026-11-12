"""Detect what this machine has: agent CLIs, provider keys (names only), ssh hosts, git projects.
Nothing here is specific to one owner; `backbone init` turns the result into a config."""
from __future__ import annotations

import os
import re
import shutil
from typing import Callable, Dict, List, Optional

AGENT_BINS = ["claude", "codex", "opencode", "qwen", "kilo", "pi", "gemini", "cline", "hermes", "goose", "crush"]
KEY_PATTERNS = {"nim": r"^NIM_\d+$", "openrouter": r"^OPENROUTER_API_KEY$", "groq": r"^GROQ_API_KEY$",
                "mistral": r"^MISTRAL_API_KEY$", "anthropic": r"^ANTHROPIC_API_KEY$", "openai": r"^OPENAI_API_KEY$"}


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
             ssh_config: str = "~/.ssh/config", project_roots: Optional[List[str]] = None) -> Dict:
    env = os.environ if env is None else env
    keys: Dict[str, List[str]] = {}
    for kind, pat in KEY_PATTERNS.items():
        names = sorted(k for k, v in env.items() if v and re.match(pat, k))
        if names:
            keys[kind] = names
    return {"agents": {a: which(a) for a in AGENT_BINS if which(a)}, "keys": keys,
            "ssh_hosts": ssh_hosts(ssh_config), "projects": git_projects(project_roots)}


def init_config(caps: Dict, base: Dict) -> Dict:
    """Derive a config from capabilities: only workers that exist, only keys that are present."""
    cfg = {**base}
    cfg["nim"] = {**base["nim"], "keys": caps["keys"].get("nim") or base["nim"]["keys"]}
    cfg["nim"]["default_key"] = cfg["nim"]["keys"][0]
    cfg["workers"] = {k: v for k, v in base["workers"].items() if k == "pi" or k in caps["agents"]}
    expert = next((a for a in ("codex", "claude") if a in caps["agents"]), "")
    cfg["escalation"] = {"expert": expert}
    cfg["hosts"] = base.get("hosts", {})
    return cfg
