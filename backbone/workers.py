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


class JcodeWorker:
    """jcode headless (`jcode run --json`) on a NIM key. Measured 2026-11-15: ~29k input tokens for a one-word task, so keep it for
    parallel-session RAM savings, not for token-cheap work. Bandit decides if it earns its place."""

    def __init__(self, cfg: dict, nim_model: str):
        self.cmd = cfg.get("cmd", "jcode")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model = nim_model

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", token: str = "", read_only: bool = False, **_) -> Result:
        t0 = time.time()
        tok = token or os.environ.get(key, "")
        if not tok:
            return Result(False, f"{key} not set", f"jcode:{key}")
        env = os.environ.copy()
        env["NVIDIA_API_KEY"] = tok
        if read_only:
            prompt = "READ-ONLY: do not edit files or run mutating commands.\n" + prompt
        try:
            p = _run([self.cmd, "run", "-p", "nvidia-nim", "-m", self.model, "--json", prompt], cwd, env, self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, f"jcode timeout after {self.timeout}s", f"jcode:{key}", key, self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        try:
            j = json.loads(p.stdout)
            text = str(j.get("text", "")).strip()
        except Exception:
            return Result(False, (p.stderr or p.stdout)[:400], f"jcode:{key}", key, lat)
        return Result(p.returncode == 0 and bool(text), text, f"jcode:{key}", key, lat, meta={"usage": j.get("usage")})


def _opencode_bin(cmd: str) -> str:
    """`opencode` on PATH, else the CLI bundled in the OpenCode desktop app (newest version dir)."""
    import glob
    import shutil
    if shutil.which(cmd):
        return cmd
    hits = sorted(glob.glob(os.path.expanduser("~/Library/Application Support/ai.opencode.desktop/cli/*/opencode-cli")))
    return hits[-1] if hits else cmd


def _main_repo(cwd: str) -> str:
    """Top of the main checkout when cwd is a linked git worktree, else ''."""
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--git-common-dir", "--git-dir"], capture_output=True, text=True, timeout=5)
        common, gdir = (r.stdout.split() + ["", ""])[:2]
        if not common or os.path.realpath(os.path.join(cwd, common)) == os.path.realpath(os.path.join(cwd, gdir)):
            return ""
        return os.path.dirname(os.path.realpath(os.path.join(cwd, common)))
    except Exception:
        return ""


def _porcelain(repo: str) -> str:
    try:
        return subprocess.run(["git", "-C", repo, "status", "--porcelain"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


class OpencodeWorker:
    """opencode headless through the local NIM proxy (launchd `local.nim-proxy`, 127.0.0.1:8787, holds the keys, so none are handled here).
    The router's own config/opencode-nim.json replaces the owner's global one (no plugins, no forced agent)."""

    def __init__(self, cfg: dict, nim_model: str, root: str):
        self.cmd = cfg.get("cmd", "opencode")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model = nim_model
        self.conf = os.path.join(root, "config", "opencode-nim.json")

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", read_only: bool = False, **_) -> Result:
        t0 = time.time()
        n = key_index(key)
        env = os.environ.copy()
        env["OPENCODE_CONFIG"] = self.conf
        # opencode resolves a git worktree to its MAIN repo and wrote there (benchmark 2026-11-15: files landed outside the isolated
        # workspace, the gate saw nothing). Pin every path to cwd in the prompt, and fail the run if the main repo's status changed.
        prompt = f"WORKSPACE: {cwd}\nUse absolute paths under {cwd} only. Never read or write outside it.\n\n{prompt}"
        main = _main_repo(cwd)
        before = _porcelain(main) if main else None
        cmd = [_opencode_bin(self.cmd), "--standalone", "run", "--agent", "plan" if read_only else "build", "--auto",
               "-m", f"nim{n}/{self.model}", prompt]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, f"opencode timeout after {self.timeout}s", f"opencode:{key}", key, self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        text = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout or "")
        text = "\n".join(l for l in text.splitlines() if not l.startswith("> ")).strip()  # drop the '> agent · model' banner
        if main and _porcelain(main) != before:
            return Result(False, f"opencode escaped its workspace and changed {main}; inspect `git -C {main} status`", f"opencode:{key}", key, lat)
        ok = p.returncode == 0 and bool(text) and "Error:" not in text[:40]
        return Result(ok, text or (p.stderr or "")[:400], f"opencode:{key}", key, lat)


class GooseWorker:
    """goose headless (`goose run --no-session --max-turns N`) on a NIM key.
    Key failover through KeyPool. ACP over HTTP (`goose serve`) available for custom UI routing on 127.0.0.1:3284.
    Oracle fit: single Rust binary, zero runtime deps, ~0.11s cold start, headless by design.
    """

    def __init__(self, cfg: dict, nim_model: str):
        self.cmd = cfg.get("cmd", "goose")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model_id = nim_model.removeprefix("nvidia/") if nim_model.startswith("nvidia/nvidia/") else nim_model

    def run(self, prompt: str, cwd: str, pool: KeyPool, prefer: Optional[str] = None, system: str = "",
            retries: int = 1, backoff_s: float = 3.0, read_only: bool = False) -> Result:
        t0 = time.time()

        def once(name: str, key: str) -> Result:
            env = os.environ.copy()
            env["NVIDIA_API_KEY"] = key
            cmd = [self.cmd, "run", "--no-session", "--max-turns", "10", prompt]
            try:
                p = _run(cmd, cwd, env, self.timeout)
            except subprocess.TimeoutExpired:
                return Result(False, f"goose timeout after {self.timeout}s on {name}: not retried", f"goose:{name}", name)
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            if p.returncode != 0 or not out:
                blob = (err or out)[:300]
                if _TRANSIENT.search(blob) or not out:
                    raise Transient(f"goose on {name}: rc={p.returncode} {blob}")
                return Result(False, blob, f"goose:{name}", name)
            return Result(True, out, f"goose:{name}", name)

        try:
            r = pool.call(once, prefer=prefer, retries=retries, backoff_s=backoff_s)
        except Transient as e:
            return Result(False, str(e), "goose", "", int((time.time() - t0) * 1000))
        r.latency_ms = int((time.time() - t0) * 1000)
        return r


class ClineWorker:
    """cline headless (`cline -p`) with the owner's own installed binary and login.
    Supports NIM key selection via NIM_1 / NIM_2 env vars for model routing."""

    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "cline")
        self.timeout = int(cfg.get("timeout_s", 900))

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", read_only: bool = False, **_) -> Result:
        t0 = time.time()
        tok = os.environ.get(key, "")
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
        if tok:
            env["NVIDIA_API_KEY"] = tok
        cmd = [self.cmd, "-p", prompt, "--output-format", "json", "--no-session-persistence",
               "--permission-mode", "plan" if read_only else "acceptEdits"]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, "cline timeout", "cline", latency_ms=self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        try:
            j = json.loads(p.stdout)
        except Exception:
            return Result(False, (p.stderr or p.stdout)[:400], "cline", latency_ms=lat)
        ok = not j.get("is_error") and p.returncode == 0
        return Result(ok, str(j.get("result", "")), "cline", latency_ms=lat,
                      meta={"cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns"), "key": key})


class AgyWorker:
    """Antigravity CLI print mode with a read-only allow-list (config/agy-allow.json): headless mode cannot prompt, so unlisted tools are denied.
    Read-only on purpose; Google quota, not NIM."""

    def __init__(self, cfg: dict, root: str):
        self.cmd = cfg.get("cmd", "agy")
        self.timeout = int(cfg.get("timeout_s", 300))
        self.conf = os.path.join(root, "config", "agy-allow.json")

    def run(self, prompt: str, cwd: str, **_) -> Result:
        t0 = time.time()
        try:
            p = _run([self.cmd, "--settings", self.conf, f"-p={prompt}"], cwd, os.environ.copy(), self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, f"agy timeout after {self.timeout}s", "agy", latency_ms=self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        out = (p.stdout or "").strip()
        ok = p.returncode == 0 and bool(out) and not out.startswith("jetski:")
        return Result(ok, out or (p.stderr or "")[:400], "agy", latency_ms=lat)
