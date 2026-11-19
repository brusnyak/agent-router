"""Library refresh: discover new sources, prune dead ones, skip unchanged trees, re-export.

Spec lives in tests/test_refresh.py. Stdlib only. Touches nothing outside the three paths it is given.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List

from backbone import sources


def _load(path: str) -> List[Dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _abs(path: str, home: str) -> str:
    return os.path.join(home, path[2:]) if path.startswith("~/") else (home if path == "~" else path)


def _signature(roots: List[Dict], home: str) -> List[list]:
    items: List[list] = []
    for root in roots:
        base = _abs(root["path"], home)
        for dp, dirs, files in os.walk(base):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(dp, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                items.append([os.path.relpath(full, home), st.st_size, int(st.st_mtime)])
    return items


def refresh(home: str, registry: str, index: str, ingest, export, now: float | None = None) -> Dict:
    home = os.path.abspath(os.path.expanduser(home))
    stamp = time.time() if now is None else now

    known = {(s.get("path"), s.get("kind")) for s in _load(registry)}
    added: List[str] = []
    for found in sources.discover(home):
        key = (found["path"], found["kind"])
        if key not in known:
            known.add(key)
            added.append(found["path"])

    kept = [{"path": p, "kind": k} for p, k in sorted(known, key=lambda x: (x[1] or "", x[0] or ""))]
    alive, pruned = [], []
    for entry in kept:
        (alive if os.path.isdir(_abs(entry["path"], home)) else pruned).append(entry)

    with open(registry, "w", encoding="utf-8") as fh:
        json.dump(alive, fh, indent=1)

    sig = _signature(alive, home)
    sig_path = index + ".sig"
    previous = None
    if os.path.exists(index) and os.path.exists(sig_path):
        try:
            with open(sig_path, encoding="utf-8") as fh:
                previous = json.load(fh)
        except (OSError, ValueError):
            previous = None

    if previous == sig:
        changed, exported = False, None
    else:
        ingest()
        exported = export(index)
        with open(sig_path, "w", encoding="utf-8") as fh:
            json.dump(sig, fh)
        changed = True

    with open(index + ".stamp", "w", encoding="utf-8") as fh:
        fh.write(str(stamp))

    return {
        "added": added,
        "pruned": [e["path"] for e in pruned],
        "changed": changed,
        "exported": exported,
    }
