"""Self-discovery of skill / agent / command sources. Walks the home directory (bounded) and finds every place that
holds routable assets, by content shape instead of a configured path:

  skill root    a dir whose children contain SKILL.md
  command root  a dir named commands/ holding *.md
  agent root    a dir named agents/ holding *.md, or any dir with >= PERSONA_MIN *.md that each start with
                frontmatter carrying name: and description: (agency-style persona repos)

Translations (docs/<lang>/), job scratch copies, caches and trash are skipped. Found roots are recorded in
~/.agent-router/sources.json, which Backbone.ingest() merges with the configured sources, so a new location needs no
config edit: run `backbone library sources --apply`."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

REGISTRY = "~/.agent-router/sources.json"
SKIP_DIRS = {"node_modules", ".git", ".Trash", "Library", ".cache", ".npm", "__pycache__", ".venv", "venv", "site-packages",
             "dist", "build", ".next", ".pyenv", ".rustup", ".cargo", "Pictures", "Movies", "Music", "Applications",
             "references", "assets", "jobs", "backups", "worktrees"}
LOCALE = re.compile(r"(^|/)(docs|doc|i18n|locales?|translations?)/[a-z]{2}(-[A-Za-z]{2,4})?(/|$)")
JUNK = re.compile(r"(\.agent-router|quarantine|backup|/\.tmp(/|$)|\.claude/projects|/memory(/|$)|/rules(/|$)|plugins/cache|/archive|/old(/|$)|-bak|\.bak)", re.I)
PERSONA_MIN = 5
MAX_DEPTH = 7
_FM = re.compile(r"\A---\s*\n(.*?)\n---", re.S)


def _persona(path: str) -> bool:
    try:
        head = open(path, encoding="utf-8", errors="replace").read(1500)
    except OSError:
        return False
    m = _FM.match(head)
    return bool(m and re.search(r"(?m)^name:", m.group(1)) and re.search(r"(?m)^description:", m.group(1)))


def discover(home: str | None = None, max_depth: int = MAX_DEPTH) -> List[Dict]:
    home = os.path.expanduser(home or "~")
    roots: Dict[tuple, int] = defaultdict(int)
    for dp, dirs, files in os.walk(home):
        rel = os.path.relpath(dp, home)
        if rel != "." and (rel.count(os.sep) >= max_depth or LOCALE.search(rel + "/") or JUNK.search(rel + "/")):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        base = os.path.basename(dp)
        mds = [f for f in files if f.endswith(".md") and not f.lower().startswith(("readme", "changelog", "contributing", "license"))]
        if "SKILL.md" in files:
            roots[(os.path.dirname(dp), "skill")] += 1
        elif base == "commands" and mds:
            roots[(dp, "command")] += len(mds)
        elif base == "agents" and mds:
            roots[(dp, "agent")] += len(mds)
        elif len(mds) >= PERSONA_MIN and sum(_persona(os.path.join(dp, f)) for f in mds[:8]) >= min(PERSONA_MIN, len(mds[:8])):
            roots[(dp, "agent")] += len(mds)
    # drop a root nested inside another root of the same kind (ingest_dir already walks recursively)
    keys = sorted(roots, key=lambda k: len(k[0]))
    kept: List[tuple] = []
    for p, kind in keys:
        if not any(kind == k2 and (p == p2 or p.startswith(p2 + os.sep)) for p2, k2 in kept):
            kept.append((p, kind))
    return [{"path": p.replace(home, "~", 1) if p.startswith(home) else p, "kind": k, "files": roots[(p, k)]} for p, k in kept]


def load_registry() -> List[Dict]:
    try:
        return json.load(open(os.path.expanduser(REGISTRY)))
    except (OSError, ValueError):
        return []


def save_registry(found: List[Dict]) -> str:
    path = os.path.expanduser(REGISTRY)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = {(s["path"], s["kind"]): s for s in load_registry()}
    merged.update({(s["path"], s["kind"]): {"path": s["path"], "kind": s["kind"]} for s in found})
    Path(path).write_text(json.dumps(sorted(merged.values(), key=lambda s: (s["kind"], s["path"])), indent=1))
    return path


def coverage(found: List[Dict], configured: List[Dict]) -> List[Dict]:
    """Mark each found root as covered when a configured/registered source of the same kind already contains it."""
    have = [(os.path.expanduser(c["path"]), c["kind"]) for c in configured]
    out = []
    for f in found:
        p = os.path.expanduser(f["path"])
        covered = any(k == f["kind"] and (p == q or p.startswith(q + os.sep)) for q, k in have)
        out.append({**f, "covered": covered})
    return out


def names_in(root: str, kind: str) -> set:
    """Cheap name list for a root: skill dir names, or file stems for agents/commands."""
    out = set()
    for dp, dirs, files in os.walk(os.path.expanduser(root)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if kind == "skill":
            if "SKILL.md" in files:
                out.add(os.path.basename(dp).lower())
        else:
            out |= {f[:-3].lower() for f in files if f.endswith(".md") and not f.lower().startswith(("readme", "changelog", "license"))}
    return out


def only_unique(found: List[Dict], known: set) -> List[Dict]:
    """Keep roots that contribute at least one name the library does not have yet (mirrors/duplicates drop out)."""
    seen, out = set(known), []
    for f in sorted(found, key=lambda x: -x["files"]):
        new = names_in(f["path"], f["kind"]) - seen
        if new:
            seen |= new
            out.append({**f, "unique": len(new)})
    return out
