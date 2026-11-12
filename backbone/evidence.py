"""Evidence check: file paths cited in a result must exist. Cheap, deterministic, no model."""
from __future__ import annotations

import os
import re
from typing import Iterable, List

EXT = r"(?:py|md|ts|tsx|js|jsx|json|ya?ml|toml|sh|sql|css|html|txt|cfg|ini|service)"
_PATH = re.compile(r"(?<![\w/.:@-])((?:~|\.{0,2})?/?(?:[\w.-]+/)*[\w.-]+\.%s)(?![\w/-])" % EXT)
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".ruff_cache", "dist", "build"}
_cache: dict = {}


def _basenames(root: str) -> set:
    if root not in _cache:
        names: set = set()
        for _, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            names.update(files)
            if len(names) > 200000:
                break
        _cache[root] = names
    return _cache[root]


def missing_paths(text: str, roots: Iterable[str]) -> List[str]:
    """Return cited paths that exist under none of `roots`. URLs, globs and placeholders are ignored."""
    roots = [os.path.realpath(r) for r in roots if r and os.path.isdir(r)]
    out: List[str] = []
    for line in text.splitlines():
        if "http://" in line or "https://" in line:
            line = re.sub(r"https?://\S+", " ", line)
        for m in _PATH.finditer(line):
            p = m.group(1).rstrip(".")
            if any(c in p for c in "*<>{}$") or p in out:
                continue
            cands = [os.path.expanduser(p)] if p.startswith(("~", "/")) else [os.path.join(r, p) for r in roots]
            if any(os.path.exists(c) for c in cands):
                continue
            if "/" not in p and any(p in _basenames(r) for r in roots):
                continue
            out.append(p)
    return out
