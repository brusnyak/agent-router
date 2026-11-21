"""Lease table: one lease per run, guarding overlapping file writes across concurrent runs.

Stored in ``~/.agent-router/data/leases.json`` guarded by ``fcntl.flock``.  Stale leases
(dead pid) are dropped on every ``acquire``.

Overlap is tested on normalised absolute paths:
  * exact equality
  * glob vs path (``fnmatch``)
  * directory prefix (one side is a directory containing the other)
  * glob vs glob: overlap if the literal prefixes before the first wildcard overlap
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
from fnmatch import fnmatch
from typing import Any

LEASE_PATH = os.path.join(os.path.expanduser("~/.agent-router"), "data", "leases.json")
_WILDCARD_RE = re.compile(r"[*?[]")


def normalize(cwd: str, pattern: str) -> str:
    """Normalise a write pattern to an absolute path under cwd."""
    p = os.path.expanduser(pattern)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def literal_prefix(glob_pattern: str) -> str:
    """Literal part of a glob before the first wildcard character."""
    m = _WILDCARD_RE.search(glob_pattern)
    return glob_pattern[:m.start()] if m else glob_pattern


def _dir_prefix(a: str, b: str) -> bool:
    """True if a is a directory prefix of b (a == b or b lives inside a)."""
    a = a.rstrip(os.sep)
    return b == a or b.startswith(a + os.sep)


def overlaps(a: str, b: str) -> bool:
    """True if two normalised absolute path patterns may denote the same file."""
    if a == b:
        return True
    aw, bw = bool(_WILDCARD_RE.search(a)), bool(_WILDCARD_RE.search(b))
    if aw and bw:
        pa, pb = literal_prefix(a), literal_prefix(b)
        if pa == pb:
            return True
        return _dir_prefix(pa, pb) or _dir_prefix(pb, pa)
    if aw:
        return fnmatch(b, a) or _dir_prefix(a.rstrip("*?["), b)
    if bw:
        return fnmatch(a, b) or _dir_prefix(b.rstrip("*?["), a)
    return _dir_prefix(a, b) or _dir_prefix(b, a)


def path_conflicts(cwd: str, patterns_a: list[str], patterns_b: list[str]) -> bool:
    return any(overlaps(normalize(cwd, x), normalize(cwd, y))
               for x in patterns_a for y in patterns_b)


def _dead(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except Exception:
        return False  # we may signal it: treat as alive
    return False


class LeaseTable:
    def __init__(self, path: str = LEASE_PATH) -> None:
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def _read(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, fh, leases: dict[str, Any]) -> None:
        fh.seek(0)
        fh.truncate()
        json.dump(leases, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())

    def acquire(self, run_id: str, cwd: str, patterns: list[str], pid: int) -> dict[str, Any] | None:
        """Register a lease for run_id.

        Returns None on success, or the conflicting holder lease (never this run_id).
        Stale leases (dead pid) are dropped first.
        """
        norm = [normalize(cwd, p) for p in patterns]
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                leases = self._read()
                leases = {k: v for k, v in leases.items() if not _dead(int(v.get("pid", 0)))}
                for holder in leases.values():
                    if holder.get("run_id") == run_id:
                        continue
                    if path_conflicts(cwd, norm, holder.get("patterns", [])):
                        return holder
                leases[run_id] = {"run_id": run_id, "cwd": cwd, "patterns": norm,
                                  "pid": pid, "ts": time.time()}
                self._write(fh, leases)
                return None
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def release(self, run_id: str) -> None:
        """Drop run_id's lease (best effort under the same lock)."""
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                leases = self._read()
                if run_id in leases:
                    del leases[run_id]
                    self._write(fh, leases)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
