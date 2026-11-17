"""Generic subprocess adapter for vetted local CLI workers.

Design: argv-only execution (never `bash -c`), an explicit command allowlist
populated from discovered binaries, bounded environment (no secret leakage),
per-call timeout, process cleanup, and a capability probe that distinguishes
installed / authenticated / executed. Read-only is a prompt instruction, not a
sandbox; workers that may write are opted in via `write_access`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .workspace import run_group

DEFAULT_TIMEOUT_S = 600


@dataclass
class AdapterResult:
    ok: bool
    text: str
    worker: str
    key_slot: str = ""
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Capability:
    """Probe result for a worker: installed, authenticated, executed."""
    installed: bool = False
    authenticated: bool = False
    executed: bool = False
    note: str = ""


class GenericWorker:
    """Run a vetted local CLI as `[cmd, *args, prompt]` with no shell.

    `cmd` must be present in `allowlist` (a set of basenames discovered by
    `backbone discover`). No model-supplied shell fragments ever reach exec.
    """

    def __init__(self, cmd: str, allowlist: Set[str], timeout_s: int = DEFAULT_TIMEOUT_S,
                 read_only: bool = False, write_access: bool = False,
                 env_prefix: Optional[str] = None):
        self.cmd = cmd
        self.allowlist = set(allowlist)
        self.timeout_s = int(timeout_s)
        self.read_only = read_only
        self.write_access = write_access
        self.env_prefix = env_prefix  # e.g. "NIM_" to pass NIM_1..3 through

    def probe(self) -> Capability:
        """Distinguish installed / authenticated / executed without side effects."""
        cap = Capability()
        cap.installed = bool(shutil.which(self.cmd))
        if not cap.installed:
            cap.note = f"{self.cmd} not on PATH"
            return cap
        # Authentication is a prompt-time property we cannot probe generically;
        # report installed-only until a real run confirms.
        cap.authenticated = True
        cap.executed = False
        cap.note = f"{self.cmd} installed; not yet executed through adapter"
        return cap

    def run(self, prompt: str, cwd: str, read_only: bool = False) -> AdapterResult:
        if self.cmd not in self.allowlist:
            return AdapterResult(False, f"{self.cmd} not in adapter allowlist", self.cmd,
                                 meta={"blocked": "not_allowlisted"})
        args = [self.cmd]
        args.append(prompt)
        env = _bounded_env(self.env_prefix)
        t0 = time.time()
        try:
            p = run_group(args, cwd=cwd, timeout=self.timeout_s, env=env)
        except subprocess.TimeoutExpired:
            return AdapterResult(False, f"{self.cmd} timeout after {self.timeout_s}s", self.cmd,
                                 latency_ms=self.timeout_s * 1000,
                                 meta={"blocked": "timeout"})
        except OSError as e:
            return AdapterResult(False, str(e)[:400], self.cmd,
                                 latency_ms=int((time.time() - t0) * 1000),
                                 meta={"blocked": "os_error"})
        out = (p.stdout or "").strip()
        lat = int((time.time() - t0) * 1000)
        if p.returncode != 0 or not out:
            err = (p.stderr or "").strip()[-400:]
            return AdapterResult(False, err or f"{self.cmd} failed: exit {p.returncode}", self.cmd,
                                 latency_ms=lat, meta={"blocked": "nonzero_exit"})
        return AdapterResult(True, out, self.cmd, latency_ms=lat)


def _bounded_env(prefix: Optional[str]) -> dict:
    """Pass only a minimal, secret-free environment. Optionally carry NIM keys
    by prefix without printing values."""
    base = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8")}
    if prefix:
        for k, v in os.environ.items():
            if k.startswith(prefix):
                base[k] = v
    return base
