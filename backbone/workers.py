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
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

from .keys import KeyPool, Transient
from .workspace import run_group

_TRANSIENT = re.compile(r"(\b429\b|\b50[0-4]\b|safety screening|queue budget|rate.?limit|timed? ?out|ECONN|overloaded)", re.I)
_TRUNCATED = re.compile(
    r"response (?:was )?truncated|model reached (?:the )?output token limit|output token limit|"
    r"(?:maximum|max)[_ ]tokens? (?:limit )?(?:reached|exceeded)|context (?:window|length).{0,40}(?:limit|exceed|truncat)",
    re.I,
)


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


def _timeout_meta(error):
    meta = {"failure_kind": "timeout", "retryable": False}
    pieces = []
    for value in (error.output, error.stderr):
        if isinstance(value, bytes):
            value = value.decode(errors='replace')
        if value:
            pieces.append(str(value))
    if pieces:
        meta['partial_output'] = '\n'.join(pieces)[-6000:]
    return meta


class PiWorker:
    def __init__(self, cfg: dict, nim_model: str):
        self.cmd = cfg.get("cmd", "pi")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model_id = nim_model
        self.thinking = str(cfg.get("thinking", "off"))
        self.use_proxy = bool(cfg.get("proxy", False))  # owner config opts in; tests stay hermetic

    def run(self, prompt: str, cwd: str, pool: KeyPool, prefer: Optional[str] = None, system: str = "",
            retries: int = 1, backoff_s: float = 3.0, read_only: bool = False) -> Result:
        t0 = time.time()

        def once(name: str, key: str) -> Result:
            env = os.environ.copy()
            isolated = tempfile.TemporaryDirectory(prefix="router-pi-")
            env["PI_CODING_AGENT_DIR"] = isolated.name
            model = self.model_id
            from .plan import _proxy_up
            from .keyproxy import PORT
            if self.use_proxy and _proxy_up(PORT):
                # key proxy up: pi gets a dummy key and a loopback base_url; the real key never enters its env or argv
                env.pop("NVIDIA_API_KEY", None)
                with open(os.path.join(isolated.name, "models.json"), "w") as fh:
                    json.dump({"providers": {"router": {"baseUrl": f"http://127.0.0.1:{PORT}/v1", "api": "openai-completions",
                                                        "apiKey": "router-local", "models": [{"id": model}]}}}, fh)
                model = "router/" + model
            else:
                env["NVIDIA_API_KEY"] = key
            cmd = [self.cmd, "-p", "--no-session", "--no-extensions", "--no-mcp", "--no-skills",
                   "--no-prompt-templates", "--thinking", self.thinking, "--model", model]
            if read_only:
                cmd += ["--tools", "read"]  # no write/edit/bash
            if system:
                cmd += ["--append-system-prompt", system]
            cmd += ["--", prompt]
            try:
                with isolated:
                    p = _run(cmd, cwd, env, self.timeout)
            except subprocess.TimeoutExpired as error:
                # not transient: another key would burn the same budget again (3 keys x timeout_s = 30 min for one stuck task)
                return Result(False, f"pi timeout after {self.timeout}s on {name}: not retried; give it a smaller scope or raise pi.timeout_s", f"pi:{name}", name, self.timeout * 1000, _timeout_meta(error))
            out = (p.stdout or "").strip()
            err = (p.stderr or "").strip()
            diagnostic = "\n".join(part for part in (err, out) if part)
            if _TRUNCATED.search(diagnostic):
                return Result(False, f"pi output truncated on {name}: {diagnostic[:300]}", f"pi:{name}", name,
                              meta={"failure_kind": "truncated", "retryable": False})
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
        self.model = cfg.get("model", "")

    def run(self, prompt: str, cwd: str, read_only: bool = False, **_) -> Result:
        t0 = time.time()
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
        cmd = [self.cmd, "-p", prompt, "--output-format", "json", "--no-session-persistence",
               "--setting-sources", "project", "--strict-mcp-config",   # no global MCP servers (flag verified in `claude --help`)
               "--permission-mode", "plan" if read_only else "acceptEdits"]
        if self.model:
            cmd += ["--model", self.model]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired:
            return Result(False, "claude timeout", "claude", latency_ms=self.timeout * 1000)
        lat = int((time.time() - t0) * 1000)
        try:
            j = json.loads(p.stdout)
        except Exception:
            return Result(False, (p.stderr or p.stdout)[:400], "claude", latency_ms=lat)
        from .model_policy import _reported_model_matches
        usage = j.get("modelUsage")
        reported = sorted(usage) if isinstance(usage, dict) and all(isinstance(k, str) for k in usage) else []
        model_matches = _reported_model_matches(self.model, reported)
        ok = not j.get("is_error") and p.returncode == 0 and model_matches
        meta = {"cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns"),
                "requested_model": self.model, "reported_models": reported,
                "model_match": model_matches}
        if not model_matches:
            meta.update(failure_kind="model_mismatch", retryable=False)
        text = str(j.get("result", "")) if model_matches else "claude requested/reported model mismatch; output not accepted"
        return Result(ok, text, "claude", latency_ms=lat, meta=meta)


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
    """OpenCode headless with a per-run direct NVIDIA NIM provider and leased key."""

    def __init__(self, cfg: dict, nim_model: str, root: str):
        self.cmd = cfg.get("cmd", "opencode")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model = nim_model

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", api_key: str = "", read_only: bool = False, **_) -> Result:
        t0 = time.time()
        if not api_key:
            return Result(False, "opencode requires an explicitly leased NIM API key", "opencode", key,
                          meta={"failure_kind": "missing_key", "retryable": False})
        env = os.environ.copy()
        env["NVIDIA_API_KEY"] = api_key
        # opencode resolves a git worktree to its MAIN repo and wrote there (benchmark 2026-11-15: files landed outside the isolated
        # workspace, the gate saw nothing). Pin every path to cwd in the prompt, and fail the run if the main repo's status changed.
        prompt = f"WORKSPACE: {cwd}\nUse absolute paths under {cwd} only. Never read or write outside it.\n\n{prompt}"
        main = _main_repo(cwd)
        before = _porcelain(main) if main else None
        config = {
            "$schema": "https://opencode.ai/config.json",
            "default_agent": "build",
            "instructions": [],
            "plugin": [],
            "provider": {
                "nim": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "NVIDIA NIM",
                    "options": {"baseURL": "https://integrate.api.nvidia.com/v1", "apiKey": "{env:NVIDIA_API_KEY}"},
                    "models": {self.model: {"name": self.model}},
                }
            },
        }
        isolated = tempfile.TemporaryDirectory(prefix="router-opencode-")
        conf = os.path.join(isolated.name, "opencode.json")
        with open(conf, "w", encoding="utf-8") as f:
            json.dump(config, f)
        env["OPENCODE_CONFIG"] = conf
        cmd = [_opencode_bin(self.cmd), "--standalone", "run", "--agent", "plan" if read_only else "build", "--auto",
               "-m", f"nim/{self.model}", prompt]
        try:
            with isolated:
                p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired as error:
            return Result(False, f"opencode timeout after {self.timeout}s", f"opencode:{key}", key,
                          self.timeout * 1000, _timeout_meta(error))
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
        self.model_id = nim_model

    def run(self, prompt: str, cwd: str, pool: KeyPool, prefer: Optional[str] = None, system: str = "",
            retries: int = 1, backoff_s: float = 3.0, read_only: bool = False) -> Result:
        t0 = time.time()

        def once(name: str, key: str) -> Result:
            env = os.environ.copy()
            env["NVIDIA_API_KEY"] = key
            cmd = [self.cmd, "run", "--no-session", "--max-turns", "10", "-t", prompt]
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


class OmpWorker:
    """oh-my-pi headless; read-only is a prompt instruction, not a sandbox."""

    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "omp")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.model = cfg.get("model", "")
        # Router runs use an isolated profile (own auth/settings) so a stale key stored in the owner's interactive omp
        # profile can never break or leak into a delegated run; the key arrives through the environment only.
        self.profile = cfg.get("profile", "router")
        self.key_env = cfg.get("key_env", "NVIDIA_API_KEY")
        # keep omp's auxiliary calls (judge, spotlight) on the active model's provider: they otherwise reach another
        # provider whose free quota may be exhausted, which blocks the whole run
        self.extra = list(cfg.get("flags", ["--offline"]))
        self.thinking = str(cfg.get("thinking", "off"))

    def run(self, prompt: str, cwd: str, read_only: bool = False, api_key: str = "") -> Result:
        t0 = time.time()
        if read_only:
            prompt += "\nREAD-ONLY: do not edit or create files"
        cmd = [self.cmd, "-p", "--no-session"]
        if self.profile and not api_key:
            cmd += ["--profile", self.profile]
        # --offline removes omp's web_search backend (verified 2026-11-18: "No web search backend ... under --offline").
        # Research runs set BACKBONE_OMP_WEB=1 to drop it; everything else keeps the quota-safe default.
        cmd += [f for f in self.extra if not (f == "--offline" and os.environ.get("BACKBONE_OMP_WEB") == "1")]
        if self.model:
            cmd += ["--model", self.model]
        cmd += ["--thinking", self.thinking]
        cmd.append(prompt)
        env = os.environ.copy()
        if api_key:
            env[self.key_env] = api_key          # never on the command line (it would show in the process list)
            isolated = tempfile.TemporaryDirectory(prefix="router-omp-")
            env["PI_CODING_AGENT_DIR"] = isolated.name
        else:
            isolated = None
        try:
            if isolated:
                with isolated:
                    p = _run(cmd, cwd, env, self.timeout)
            else:
                p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired as error:
            return Result(False, f"omp timeout after {self.timeout}s", "omp", latency_ms=self.timeout * 1000,
                          meta=_timeout_meta(error))
        except OSError as e:
            return Result(False, str(e)[-400:], "omp", latency_ms=int((time.time() - t0) * 1000))
        out = (p.stdout or "").strip()
        out = re.sub(r"^Working\.\.\.[^\n]*(?:\n|$)", "", out, count=1).strip()
        lat = int((time.time() - t0) * 1000)
        if p.returncode != 0 or not out:
            err = (p.stderr or "").strip()[-400:]
            return Result(False, err or f"omp failed: exit {p.returncode}, empty or unsuccessful output", "omp", latency_ms=lat)
        return Result(True, out, "omp", latency_ms=lat)


class ClineWorker:
    """cline headless (`cline [--plan] --cwd DIR PROMPT`, verified against `cline --help` 3.0.74) with the owner's installed binary and login.
    Supports NIM key selection via NIM_1 / NIM_2 env vars for model routing."""

    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "cline")
        self.timeout = int(cfg.get("timeout_s", 900))
        self.flags = list(cfg.get("flags", []))   # e.g. ["--provider", "<id>", "--model", "<id>"]; a key never goes on argv

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", token: str = "", api_key: str = "", read_only: bool = False, **_) -> Result:
        t0 = time.time()
        if api_key:
            flags = self.flags
            provider = ""
            model = ""
            for i, flag in enumerate(flags):
                if flag in ("--provider", "-P") and i + 1 < len(flags):
                    provider = str(flags[i + 1]).lower()
                elif flag.startswith("--provider="):
                    provider = flag.split("=", 1)[1].lower()
                if flag in ("--model", "-m") and i + 1 < len(flags):
                    model = str(flags[i + 1])
                elif flag.startswith("--model="):
                    model = flag.split("=", 1)[1]
            if not provider or not (provider == "nim" or provider == "nvidia" or provider.startswith("nvidia-")) or not model:
                return Result(False, "cline explicit NIM key requires flags: --provider nvidia|nim --model <NIM model>",
                              "cline", key, int((time.time() - t0) * 1000),
                              {"failure_kind": "missing_nim_provider", "retryable": False})
            if any(flag in ("-k", "--key") or flag.startswith("--key=") for flag in flags):
                return Result(False, "cline --key persists credentials; remove it and use the leased NVIDIA_API_KEY environment value",
                              "cline", key, int((time.time() - t0) * 1000),
                              {"failure_kind": "unsafe_key_flag", "retryable": False})
        tok = api_key or token or os.environ.get(key, "")
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")}
        if tok:
            env["NVIDIA_API_KEY"] = tok
        cmd = [self.cmd]
        if read_only:
            cmd.append("--plan")                 # cline: -p/--plan = plan mode (no edits); the prompt is positional
        cmd += ["--cwd", cwd] + self.flags + [prompt]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired as error:
            return Result(False, "cline timeout", "cline", key, self.timeout * 1000,
                          _timeout_meta(error))
        lat = int((time.time() - t0) * 1000)
        try:
            j = json.loads(p.stdout)
        except Exception:
            return Result(False, (p.stderr or p.stdout)[:400], "cline", key, lat)
        ok = not j.get("is_error") and p.returncode == 0
        return Result(ok, str(j.get("result", "")), "cline", key, lat,
                      meta={"cost_usd": j.get("total_cost_usd"), "turns": j.get("num_turns")})


class OpenHandsWorker:
    """OpenHands agent-server over HTTP (no Docker). Communicates with a running
    agent-server instance via REST API: POST /api/conversations -> /{id}/run ->
    poll /{id}/execution_status -> GET /{id} for results.

    Server must be running separately (systemd openhands.service on Oracle).
    Config: openhands { base_url: http://127.0.0.1:8000, timeout_s: 600 }
    NIM key is configured on the server side (LLM_API_KEY env), not here.
    """

    def __init__(self, cfg: dict):
        self.base_url = cfg.get("base_url", "http://127.0.0.1:8000").rstrip("/")
        self.timeout = int(cfg.get("timeout_s", 600))

    def run(self, prompt: str, cwd: str, read_only: bool = False, **_) -> Result:
        import urllib.request
        import urllib.error

        t0 = time.time()

        def _req(method: str, path: str, data: dict | None = None, timeout: int = 10):
            url = f"{self.base_url}{path}"
            body = None
            headers = {"Content-Type": "application/json"}
            if data is not None:
                body = json.dumps(data).encode()
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode(errors="replace")[:500]
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                return 0, str(e)

        def _poll(conv_id: str, max_poll_s: int = 300):
            """Poll execution_status until done or timeout."""
            import time as _t
            deadline = _t.time() + max_poll_s
            while _t.time() < deadline:
                status, body = _req("GET", f"/api/conversations/{conv_id}/execution_status", timeout=10)
                if status == 200:
                    try:
                        j = json.loads(body)
                        state = j.get("state", "")
                        if state in ("finished", "completed", "done"):
                            return "done", j
                        if state in ("failed", "error", "rejected"):
                            return "error", j
                        if state in ("running", "pending", "started"):
                            _t.sleep(3)
                            continue
                    except Exception:
                        pass
                _t.sleep(3)
            return "timeout", {}

        try:
            # 1. Create conversation
            status, body = _req("POST", "/api/conversations", {
                "initial_message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
                "metadata": {"source": "backbone", "cwd": cwd},
                "workspace": {"working_dir": cwd, "kind": "LocalWorkspace"},
                "agent_settings": {"agent_kind": "openhands"},
            }, timeout=15)
            if status not in (200, 201):
                return Result(False, f"openhands create failed: rc={status} {body[:300]}", "openhands", latency_ms=int((time.time()-t0)*1000))

            try:
                conv = json.loads(body)
                conv_id = conv.get("id") or conv.get("conversation_id")
            except Exception:
                return Result(False, f"openhands create: cannot parse id from {body[:200]}", "openhands", latency_ms=int((time.time()-t0)*1000))

            if not conv_id:
                return Result(False, f"openhands create: no id in {body[:200]}", "openhands", latency_ms=int((time.time()-t0)*1000))

            # 2. Run the conversation
            status, body = _req("POST", f"/api/conversations/{conv_id}/run", timeout=15)
            if status not in (200, 202, 409):  # 409 = already running: proceed to poll
                return Result(False, f"openhands run failed: rc={status} {body[:300]}", f"openhands:{conv_id}", latency_ms=int((time.time()-t0)*1000))

            # 3. Poll for completion
            poll_state, poll_data = _poll(conv_id, max_poll_s=self.timeout - 30)
            if poll_state != "done":
                return Result(False, f"openhands poll: {poll_state} for {conv_id}", f"openhands:{conv_id}", latency_ms=int((time.time()-t0)*1000))

            # 4. Fetch results
            status, body = _req("GET", f"/api/conversations/{conv_id}", timeout=15)
            if status != 200:
                return Result(False, f"openhands fetch failed: rc={status} {body[:300]}", f"openhands:{conv_id}", latency_ms=int((time.time()-t0)*1000))

            try:
                conv_data = json.loads(body)
            except Exception:
                conv_data = {}

            # Extract the assistant's final response
            output = ""
            messages = conv_data.get("messages", [])
            if isinstance(messages, list):
                for m in reversed(messages):
                    if isinstance(m, dict) and m.get("role") == "assistant":
                        output = m.get("content", "") or m.get("text", "") or ""
                        break
            if not output:
                output = str(conv_data.get("output", "") or conv_data.get("result", "") or body[:500])

            ok = bool(output) and "Error" not in output[:50]
            return Result(ok, output[:5000], f"openhands:{conv_id}", latency_ms=int((time.time()-t0)*1000),
                         meta={"conversation_id": conv_id})

        except Exception as e:
            return Result(False, f"openhands error: {str(e)[:300]}", "openhands", latency_ms=int((time.time()-t0)*1000))


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


class NimCallWorker:
    """Tool-free NIM chat through the router's single authoritative KeyPool."""

    def __init__(self, cfg: dict, nim_model: str, base_url: str = "https://integrate.api.nvidia.com/v1"):
        self.model = nim_model
        self.timeout = int(cfg.get("timeout_s", 120))
        self.max_tokens = int(cfg.get("max_tokens", 4096))
        self.base_url = base_url

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", token: str = "", read_only: bool = False, pool=None, **_) -> Result:
        t0 = time.time()
        if pool is None or not hasattr(pool, "call"):
            return Result(False, "nim-chat requires the router KeyPool", "nim-chat", key,
                          int((time.time() - t0) * 1000), {"failure_kind": "missing_key_pool", "retryable": False})
        from . import nim
        selected = {"key": key}
        # nim.chat owns HTTP, transient classification, and the sole KeyPool lease.
        try:
            text = nim.chat(pool, [{"role": "user", "content": prompt}], base_url=self.base_url,
                            model=self.model, max_tokens=self.max_tokens, prefer=key, retries=1,
                            backoff_s=3.0, timeout=self.timeout,
                            on_key=lambda name: selected.update(key=name))
        except Transient as e:
            return Result(False, str(e), "nim-chat", selected['key'], int((time.time() - t0) * 1000))
        except RuntimeError as e:
            return Result(False, str(e), "nim-chat", selected['key'], int((time.time() - t0) * 1000),
                          {"failure_kind": "truncated" if "finish_reason=length" in str(e) else "provider_error", "retryable": False})
        lat = int((time.time() - t0) * 1000)
        return Result(True, text, "nim-chat", selected['key'], lat)



class PersonaWorker:
    """ECC persona / agency agent lane: reads a persona .md file, injects it as system
    context, and runs the task through NIM chat inside KeyPool call.
    Selectable via @ecc-<persona> or @agency-<agent>; falls back to available NIM key
    when a specific key is down."""

    def __init__(self, cfg: dict, nim_model: str):
        self.model = nim_model
        self.timeout = int(cfg.get("timeout_s", 120))

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", token: str = "",
            read_only: bool = False, pool=None, persona_path: str = "", **_) -> Result:
        t0 = time.time()
        try:
            sys.path.insert(0, os.path.expanduser("~/Developer/agent-router/scripts"))
            from nim_call import chat
        except Exception as e:
            return Result(False, f"nim_call import failed: {e}", "persona", latency_ms=int((time.time() - t0) * 1000))

        persona_ctx = ""
        if persona_path:
            try:
                with open(os.path.expanduser(persona_path), encoding="utf-8", errors="ignore") as fh:
                    persona_ctx = fh.read()[:3000]
            except OSError:
                persona_ctx = ""

        full_prompt = prompt
        if persona_ctx:
            full_prompt = (
                f"## Persona context (follow this role definition)\n{persona_ctx}\n\n"
                f"## Task\n{prompt}"
            )

        def _chat(kname: str, kval: str):
            key_order = [kname] + [k for k in ("NIM_3", "NIM_2", "NIM_1") if k != kname]
            try:
                msg = chat(self.model, [{"role": "user", "content": full_prompt}],
                           timeout=self.timeout, max_tokens=1500, key_order=key_order)
            except RuntimeError as e:
                text = str(e)
                if _TRANSIENT.search(text):
                    raise Transient(text)
                raise
            out = (msg.get("content") or "").strip()
            if not out:
                raise Transient("empty NIM response")
            return out

        try:
            if pool is not None:
                text = pool.call(_chat, prefer=key, retries=1, backoff_s=3.0)
            else:
                kname = key
                kval = os.environ.get(kname, "")
                env = os.environ.copy()
                env[kname] = kval
                try:
                    msg = chat(self.model, [{"role": "user", "content": full_prompt}],
                               timeout=self.timeout, max_tokens=1500)
                except RuntimeError as e:
                    text = str(e)
                    if _TRANSIENT.search(text):
                        return Result(False, text, "persona", kname, int((time.time() - t0) * 1000))
                    raise
                text = (msg.get("content") or "").strip()
                if not text:
                    return Result(False, "empty NIM response", "persona", kname, int((time.time() - t0) * 1000))
        except Transient as e:
            return Result(False, str(e), "persona", key, int((time.time() - t0) * 1000))
        lat = int((time.time() - t0) * 1000)
        return Result(bool(text), text, "persona", key, lat)
class KiloWorker:
    """Kilo headless (`kilo run <message>`): pure local agent run without external plugins.
    No keys travel on argv; an explicitly leased NIM/OpenAI-compatible API key arrives through
    the environment only. Works with any provider reachable through Kilo's model config, not
    just NVIDIA. Failover across leased keys through KeyPool.

    Read-only is honored via --pure (no plugins) plus the instruction not to edit files;
    Kilo has no plan-only mode, so write operations are bounded by the prompt contract.
    """

    def __init__(self, cfg: dict):
        self.cmd = cfg.get("cmd", "kilo")
        self.timeout = int(cfg.get("timeout_s", 600))
        self.flags = list(cfg.get("flags", ["--pure"]))

    def run(self, prompt: str, cwd: str, key: str = "NIM_1", api_key: str = "",
            read_only: bool = False, **_) -> Result:
        t0 = time.time()
        if not api_key:
            return Result(False, "kilo requires an explicitly leased API key", "kilo", key,
                          meta={"failure_kind": "missing_key", "retryable": False})
        env = os.environ.copy()
        env["API_KEY"] = api_key
        prompt = f"WORKSPACE: {cwd}\nUse absolute paths under {cwd} only. Never read or write outside it.\n{'' if not read_only else 'READ-ONLY: do not edit or create files.\n'}{prompt}"
        main = _main_repo(cwd)
        before = _porcelain(main) if main else None
        cmd = [self.cmd, "run", *self.flags, "--model", f"nim/{key}", prompt]
        try:
            p = _run(cmd, cwd, env, self.timeout)
        except subprocess.TimeoutExpired as error:
            return Result(False, f"kilo timeout after {self.timeout}s", f"kilo:{key}", key,
                          self.timeout * 1000, _timeout_meta(error))
        lat = int((time.time() - t0) * 1000)
        text = re.sub(r"\x1b\[[0-9;]*m", "", p.stdout or "").strip()
        if main and _porcelain(main) != before:
            return Result(False, f"kilo escaped its workspace and changed {main}; inspect `git -C {main} status`", f"kilo:{key}", key, lat)
        ok = p.returncode == 0 and bool(text) and "Error:" not in text[:40]
        return Result(ok, text or (p.stderr or "")[:400], f"kilo:{key}", key, lat)
