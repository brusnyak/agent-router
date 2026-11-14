"""Workers: one harness process per task. The router fans out; harnesses never spawn sub-agents.

  pi[:NIM_n]  Pi coding agent on a NIM key (read/edit/bash tools). Key failover through KeyPool.
  claude      `claude -p` with the owner's own installed binary and login (no token handling here).
  codex       `codex exec` likewise.
Each returns Result; Transient is raised only for failures worth retrying on another key.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

from .keys import KeyPool, Transient
from .workspace import run_group

_TRANSIENT = re.compile(r"(\b429\b|\b50[0-4]\b|safety screening|queue budget|rate.?limit|timed? ?out|ECONN|overloaded)", re.I)


@dataclass
class Result:
    ok: bool
    text: str
    worker: str
    key_slot: str = ""
    latency_ms: int = 0
    meta: dict = field(default_factory=dict)


def _resolve(cmd: list) -> list:
    """Bare command not on PATH: fall back to the repo-local <repo>/.tools/<cmd> (how the VM ships pi)."""
    import shutil
    local = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tools", cmd[0])
    return [local, *cmd[1:]] if not os.sep in cmd[0] and not shutil.which(cmd[0]) and os.path.exists(local) else cmd


def _run(cmd: list, cwd: str, env: dict, timeout: int) -> subprocess.CompletedProcess:
    cmd = _resolve(cmd)
    try:
        return run_group(cmd, cwd=cwd, timeout=timeout, env=env)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", f"worker binary not found: {cmd[0]}")


def key_index(name: str) -> str:
    m = re.search(r"(\d+)$", name)
    return m.group(1) if m else "1"


class PiWorker:
    def __init__(self, cfg: dict, nim_model: str):
        self.cmd = cfg.get("cmd", "pi")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model_id = nim_model.removeprefix("nvidia/") if nim_model.startswith("nvidia/nvidia/") else nim_model

    def run(self, prompt: str, cwd: str, pool: KeyPool, prefer: Optional[str] = None, system: str = "",
            retries: int = 1, backoff_s: float = 3.0, read_only: bool = False) -> Result:
        t0 = time.time()

        def once(name: str, key: str) -> Result:
            env = os.environ.copy()
            env[name] = key
            model = f"nim{key_index(name)}/{self.model_id}"
            cmd = [self.cmd, "-p", "--no-session", "--no-extensions", "--no-mcp", "--no-skills",
                   "--no-prompt-templates", "--model", model]
            if read_only:
                cmd += ["--tools", "read"]  # no write/edit/bash
            if system:
                cmd += ["--append-system-prompt", system]
            cmd += ["--", prompt]
            try:
                p = _run(cmd, cwd, env, self.timeout)
            except subprocess.TimeoutExpired:
                # not transient: another key would burn the same budget again (3 keys x timeout_s = 30 min for one stuck task)
                return Result(False, f"pi timeout after {self.timeout}s on {name}: not retried; give it a smaller scope or raise pi.timeout_s", f"pi:{name}", name)
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            if p.returncode != 0 or not out:
                blob = (err or out)[:300]
                if _TRANSIENT.search(blob) or not out:
                    raise Transient(f"pi on {name}: rc={p.returncode} {blob}")
                return Result(False, blob, f"pi:{name}", name)
            return Result(True, out, f"pi:{name}", name)

        try:
            r = pool.call(once, prefer=prefer, retries=retries, backoff_s=backoff_s)
        except Transient as e:
            return Result(False, str(e), "pi", "", int((time.time() - t0) * 1000))
        r.latency_ms = int((time.time() - t0) * 1000)
        return r


def _pi_fixed(self, prompt, cwd, env_name, model, read_only=True):
    t0 = time.time()
    env = os.environ.copy()
    cmd = [self.cmd, "-p", "--no-session", "--no-extensions", "--no-mcp", "--no-skills", "--no-prompt-templates", "--model", model]
    if read_only:
        cmd += ["--tools", "read"]
    cmd += ["--", prompt]
    if not env.get(env_name):
        return Result(False, f"{env_name} not set", model)
    try:
        p = _run(cmd, cwd, env, self.timeout)
    except subprocess.TimeoutExpired:
        return Result(False, "timeout", model, latency_ms=self.timeout * 1000)
    out = (p.stdout or "").strip()
    return Result(p.returncode == 0 and bool(out), out or (p.stderr or "")[:300], model, latency_ms=int((time.time() - t0) * 1000))


PiWorker.run_fixed = _pi_fixed


class ClaudeWorker:
    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "claude")
        self.timeout = int(cfg.get("timeout_s", 900))

    def run(self, prompt: str, cwd: str, read_only: bool = False, **_) -> Result:
        t0 = time.time()
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
        cmd = [self.cmd, "-p", prompt, "--output-format", "json", "--no-session-persistence",
               "--setting-sources", "project", "--permission-mode", "plan" if read_only else "acceptEdits"]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, "claude timeout", "claude", latency_ms=self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        try:
            j = json.loads(p.stdout)
        except Exception:
            return Result(False, (p.stderr or p.stdout)[:400], "claude", latency_ms=lat)
        ok = not j.get("is_error") and p.returncode == 0
        return Result(ok, str(j.get("result", "")), "claude", latency_ms=lat,
                      meta={"cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns")})


class CodexWorker:
    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "codex")
        self.timeout = int(cfg.get("timeout_s", 900))

    def run(self, prompt: str, cwd: str, read_only: bool = False, **_) -> Result:
        t0 = time.time()
        with tempfile.NamedTemporaryFile("r", suffix=".txt", delete=False) as f:
            last = f.name
        cmd = [self.cmd, "exec", "--ephemeral", "-s", "read-only" if read_only else "workspace-write",
               "-C", cwd, "-o", last, "--skip-git-repo-check", prompt]
        try:
            p = _run(cmd, cwd, os.environ.copy(), self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, "codex timeout", "codex", latency_ms=self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        try:
            text = open(last).read().strip()
        finally:
            try:
                os.unlink(last)
            except OSError:
                pass
        ok = p.returncode == 0 and bool(text)
        return Result(ok, text or (p.stderr or p.stdout)[:400], "codex", latency_ms=lat)
