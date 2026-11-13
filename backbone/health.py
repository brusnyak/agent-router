"""Doctor result persistence + worker health lookup. Pure functions, no DB. Unknown = allowed."""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Iterable, Optional


def save(path: str, result: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump({**result, "saved_at": time.time()}, f, indent=2)


def usable(path: str, worker: str, max_age_s: int = 21600) -> bool:
    try:
        d = json.load(open(path))
        if time.time() - float(d["saved_at"]) > max_age_s:
            return True
        return not any(r.get("name") == worker and r.get("usable") is False for r in d.get("agents", []))
    except Exception:
        return True


def pick(order: Iterable[str], usable_fn: Callable[[str], bool]) -> Optional[str]:
    return next((w for w in order if usable_fn(w)), None)


def rewrite_gate(gate: str, repo_root: str) -> str:
    if not gate:
        return gate
    first, sep, rest = gate.partition(" ")
    if first.startswith((".venv/", "./")):
        first = os.path.join(os.path.abspath(repo_root), first[2:] if first.startswith("./") else first)
    return first + sep + rest
