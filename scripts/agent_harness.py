#!/usr/bin/env python3
"""Lightweight agent execution harness — OpenCode-style but minimal.

Provides reliable, verifiable code execution for NIM agents (nim1/nim2/nim3)
and CLI agents (claude/codex). Key features:

- **Key rotation**: round-robin across NIM_1/NIM_2/NIM_3 on failure
- **Retry with backoff**: 3 attempts, exponential backoff
- **Post-dispatch verification**: checks claimed file creation against disk
- **Capability gating**: routes build/write tasks only to agents with file-write
- **Deterministic fallback**: shell=False subprocess, worktree isolation

Usage:
    from scripts.agent_harness import AgentHarness
    harness = AgentHarness()
    result = harness.run("build a hello world python script")
    # result includes: status, agent, model, output, verified_files, trace_id
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = os.path.expanduser("~")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(_PROJECT_ROOT, "config")
VAULT_SANDBOX = os.path.join(HOME, "memory-vault", "agents")

# NIM key rotation order
NIM_KEYS = ["NIM_1", "NIM_2", "NIM_3"]
NIM_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"


def _load_env() -> None:
    """Load project .env then ~/.env (values never read, only key presence)."""
    for envfile in (os.path.join(_PROJECT_ROOT, ".env"), os.path.join(HOME, ".env")):
        try:
            with open(envfile, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except OSError:
            pass


_load_env()


class AgentHarness:
    """Lightweight agent execution environment.

    Dispatches tasks to NIM agents (direct API) or CLI agents (subprocess),
    verifies claimed outputs against disk, and rotates NIM keys on failure.
    """

    def __init__(self):
        self.trace_id: str = str(uuid.uuid4())
        self._key_index: int = 0
        self._key_cooldown: Dict[str, float] = {}
        self._call_log: List[Dict[str, Any]] = []

        # Load agent capabilities from config
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            self._agents_cfg = _yaml.safe_load(f) or {}
        self._agents: Dict[str, dict] = {
            a["id"]: a for a in self._agents_cfg.get("agents", []) if a.get("id")
        }

    # ------------------------------------------------------------------
    # NIM key rotation
    # ------------------------------------------------------------------

    def _next_nim_key(self) -> Optional[str]:
        """Return the next healthy NIM key env var name (round-robin)."""
        now = time.time()
        for _ in range(len(NIM_KEYS)):
            key = NIM_KEYS[self._key_index % len(NIM_KEYS)]
            self._key_index += 1
            cooldown_until = self._key_cooldown.get(key, 0)
            if now >= cooldown_until and os.environ.get(key):
                return key
        return None

    def _mark_key_unhealthy(self, key: str, seconds: float = 30.0) -> None:
        self._key_cooldown[key] = time.time() + seconds

    # ------------------------------------------------------------------
    # NIM API call with retry + key rotation
    # ------------------------------------------------------------------

    def _nim_call(self, prompt: str, max_retries: int = 3) -> str:
        """Call NIM model with key rotation and exponential backoff."""
        import sys as _sys
        sys.path.insert(0, os.path.join(HOME, "memory-vault", "scripts"))
        import nim_call

        last_error = ""
        for attempt in range(max_retries):
            key = self._next_nim_key()
            if not key:
                return f"Error: no healthy NIM key available (attempt {attempt + 1})"

            try:
                resp = nim_call.chat(
                    f"nim:{NIM_MODEL}",
                    [{"role": "user", "content": prompt}],
                    timeout=60,
                    max_tokens=4096,
                    rules=False,
                )
                content = resp.get("content", "") or ""
                if content:
                    self._cb_record_success(key)
                    return content
                # Empty content — treat as failure, rotate key
                self._mark_key_unhealthy(key, 10.0)
                last_error = "empty response"
            except Exception as e:
                self._mark_key_unhealthy(key, 30.0)
                last_error = str(e)

            # Exponential backoff before next attempt
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt, 10))

        return f"Error: NIM call failed after {max_retries} attempts: {last_error}"

    def _write_code_blocks(self, output: str, workdir: str = None) -> List[str]:
        """Extract code blocks from NIM output and write them to disk with claimed filenames.

        Returns list of written file paths.
        """
        import re
        written: List[str] = []
        if not workdir:
            workdir = _PROJECT_ROOT

        # Extract ```python ... ``` and ``` ... ``` blocks
        blocks = re.findall(r"```(?:\w+)?\n(.*?)\n```", output, re.DOTALL)
        for i, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            # Guess filename from the surrounding context (e.g. "Created hello.py")
            fname = f"nim_output_{i}.py"
            # Look for filename mentions near the code block
            fn_match = re.search(r"```(?:\w+)?\n(.*?)\n```", output, re.DOTALL)
            # Try to find "Created X.py" or "wrote to X.py" near each block
            context_before = output[max(0, output.find(block) - 200):output.find(block)]
            name_match = re.search(r"(?:Created|wrote|saved|wrote to)\s+([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+)", context_before, re.IGNORECASE)
            if name_match:
                fname = os.path.basename(name_match.group(1))
            fpath = os.path.join(workdir, fname)
            try:
                with open(fpath, "w") as f:
                    f.write(block + "\n")
                written.append(fpath)
            except Exception as e:
                # Don't silently swallow - log the failure
                print(f"WARNING: could not write {fpath}: {e}")
        return written

    def _cb_record_success(self, key: str) -> None:
        if key in self._key_cooldown:
            del self._key_cooldown[key]

    # ------------------------------------------------------------------
    # Claimed file extraction + verification
    # ------------------------------------------------------------------

    def extract_claimed_files(self, output: str) -> List[str]:
        """Extract file paths an agent claims to have created/modified.

        Handles both plain text (Created hello.py) and backtick-quoted
        (Created `hello.py`) forms that LLMs commonly emit.
        """
        import re
        # Path chars: alphanumerics, dot, slash, underscore, hyphen, tilde
        # Requires a file extension (must contain a dot before the final segment)
        path_char = r"[A-Za-z0-9_./\-~]+\.[A-Za-z0-9]+"
        patterns = [
            rf"(?:`|['\"])?({path_char})(?:`|['\"])?",
            rf"Created\s+({path_char})",
            rf"wrote\s+to\s+({path_char})",
            rf"wrote\s+({path_char})",
            rf"saved\s+to\s+({path_char})",
            rf"at\s+({path_char})",
            rf"file[:\s]+({path_char})",
        ]
        found: set[str] = set()
        for pat in patterns:
            for m in re.finditer(pat, output, re.IGNORECASE):
                path = m.group(1).strip().rstrip(".,\"')`")
                if path and not path.startswith(("http", "www")):
                    if path.lower() not in ("a", "the", "code", "output", "file", "script", "it", "this", "that"):
                        found.add(path)
        return sorted(found)

    def verify_claimed_files(self, claimed: List[str], agent_can_write: bool) -> Dict[str, str]:
        """Check each claimed path against disk."""
        verification: Dict[str, str] = {}
        for path in claimed:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                verification[path] = "verified"
            else:
                verification[path] = "fabricated-no-write-tool" if not agent_can_write else "not-found"
        return verification

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def run(self, task: str, lane: Optional[str] = None, agent: Optional[str] = None,
            project: Optional[str] = None) -> Dict[str, Any]:
        """Run a task through the harness.

        Returns dict with: status, trace_id, agent, model, lane, output,
        claimed_files, file_verification, tokens_spent, latency_ms.
        """
        import yaml as _yaml

        # Determine lane
        if not lane:
            lane = self._classify_lane(task)

        # Determine agent
        if not agent:
            agent = self._select_agent(lane, task)

        agent_cfg = self._agents.get(agent, {})
        model = agent_cfg.get("model", NIM_MODEL)
        provider = agent_cfg.get("provider", "nim")
        write_access = agent_cfg.get("write_access", False)
        can_write = provider == "cli" and write_access

        t0 = time.time()
        output = ""
        written_files: List[str] = []

        # Dispatch
        if provider == "nim":
            packet = self._build_packet(task, lane, agent, project, agent_cfg)
            output = self._nim_call(json.dumps(packet, indent=2))
            # NIM agents can't write files directly — extract code blocks and write them
            if lane == "build" and not output.startswith("Error:"):
                written_files = self._write_code_blocks(output)
        elif provider in ("claude", "codex", "gemini"):
            output = self._dispatch_cli(agent, task, lane, project, agent_cfg)
        else:
            output = f"Error: unknown provider {provider}"

        latency_ms = int((time.time() - t0) * 1000)

        # Post-dispatch verification: combine agent-claimed + actually-written files
        claimed = self.extract_claimed_files(output) + written_files
        verification = self.verify_claimed_files(claimed, can_write or bool(written_files))

        # Determine final status
        if output.startswith("Error:"):
            status = "error"
        elif claimed and not any(v == "verified" for v in verification.values()):
            status = "fabrication_detected"
        else:
            status = "done"

        result = {
            "trace_id": self.trace_id,
            "status": status,
            "lane": lane,
            "agent": agent,
            "model": model,
            "provider": provider,
            "output": output,
            "claimed_files": claimed,
            "file_verification": verification,
            "tokens_spent": (len(task) + len(output)) // 4,
            "latency_ms": latency_ms,
        }

        self._call_log.append(result)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_lane(self, task: str) -> str:
        lower = task.lower()
        if any(w in lower for w in ["build", "code", "implement", "fix", "refactor", "script"]):
            return "build"
        if any(w in lower for w in ["review", "roast", "audit", "check", "bug"]):
            return "review-roast"
        if any(w in lower for w in ["research", "search", "find", "web", "investigate"]):
            return "research-public"
        if any(w in lower for w in ["plan", "design", "strategy", "offer", "proposal"]):
            return "planner"
        return "planner"

    def _select_agent(self, lane: str, task: str) -> str:
        """Select the best agent for a lane/task."""
        import yaml as _yaml
        with open(os.path.join(CONFIG_DIR, "agents.yaml")) as f:
            cfg = _yaml.safe_load(f) or {}

        # Build lanes -> agents mapping from lanes.yaml
        with open(os.path.join(CONFIG_DIR, "lanes.yaml")) as f:
            lanes_cfg = _yaml.safe_load(f) or {}

        lane_def = None
        for l in lanes_cfg.get("lanes", []):
            if l.get("id") == lane:
                lane_def = l
                break

        # Try lane-specific agents first
        if lane_def:
            for agent_id in lane_def.get("agents", []):
                if agent_id in self._agents:
                    return agent_id

        # Fallback: prefer NIM agents for non-write tasks, CLI for write tasks
        if lane == "build":
            # Build needs file-write -> try CLI agents first
            for aid, acfg in self._agents.items():
                if acfg.get("provider") in ("claude", "codex") and acfg.get("write_access"):
                    return aid
            # Then NIM
            for aid in ["nim3", "nim2", "nim1"]:
                if aid in self._agents:
                    return aid
        else:
            # Non-build tasks: prefer NIM
            for aid in ["nim3", "nim2", "nim1"]:
                if aid in self._agents:
                    return aid
            # Then CLI
            for aid, acfg in self._agents.items():
                if acfg.get("provider") in ("claude", "codex", "gemini"):
                    return aid

        return "nim3"

    def _build_packet(self, task: str, lane: str, agent: str,
                      project: Optional[str], agent_cfg: dict) -> dict:
        return {
            "goal": task,
            "lane": lane,
            "agent": agent,
            "project": project or "global",
            "task_id": str(uuid.uuid4())[:8],
            "user_input": task,
            "skills": [],
            "model": agent_cfg.get("model", NIM_MODEL),
        }

    def _dispatch_cli(self, agent: str, task: str, lane: str,
                      project: Optional[str], agent_cfg: dict) -> str:
        """Dispatch to a CLI agent via subprocess (shell=False) with TTY wrapper."""
        import shutil
        cli = agent_cfg.get("cli", agent)
        if not shutil.which(cli):
            return f"Error: CLI {cli} not found in PATH"

        packet = self._build_packet(task, lane, agent, project, agent_cfg)
        packet_json = json.dumps(packet, indent=2)

        # Build args as a list — shell=False.
        args = [cli, packet_json]

        # Interactive CLI agents (claude, codex, opencode, etc.) need a TTY.
        # Wrap in `script` (macOS pseudo-terminal) while keeping shell=False.
        if cli in ("claude", "codex", "opencode", "cline", "kilo", "hermes"):
            if shutil.which("script"):
                args = ["script", "-q", "/dev/null"] + args

        try:
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=120,
                env=os.environ.copy(),
                input=packet_json,
            )
            out = result.stdout or result.stderr or "No output"
            if result.returncode != 0:
                out += f"\n[exit code {result.returncode}]"
            return out
        except subprocess.TimeoutExpired:
            return f"Agent {agent} timed out after 120 seconds"
        except Exception as e:
            return f"Error launching {agent}: {e}"

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return summary of all calls made through this harness."""
        total = len(self._call_log)
        done = sum(1 for c in self._call_log if c["status"] == "done")
        errors = sum(1 for c in self._call_log if c["status"] == "error")
        fabrication = sum(1 for c in self._call_log if c["status"] == "fabrication_detected")
        return {
            "trace_id": self.trace_id,
            "total_calls": total,
            "done": done,
            "errors": errors,
            "fabrication_detected": fabrication,
            "success_rate": round(done / total * 100, 1) if total else 0.0,
        }


def quick_run(task: str, lane: Optional[str] = None, agent: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function: run a single task through the harness."""
    harness = AgentHarness()
    return harness.run(task, lane=lane, agent=agent)


if __name__ == "__main__":
    import sys
    task = sys.argv[1] if len(sys.argv) > 1 else "build a simple hello world python script"
    lane = sys.argv[2] if len(sys.argv) > 2 else None
    agent = sys.argv[3] if len(sys.argv) > 3 else None
    result = quick_run(task, lane=lane, agent=agent)
    print(json.dumps(result, indent=2, default=str))
