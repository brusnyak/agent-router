"""Run a task on a remote host that has its own backbone install, over ssh. Config: hosts.<name> {ssh, dir, env, pythonpath}."""
from __future__ import annotations

import json
import shlex
import subprocess
from typing import Dict


def build_command(host: Dict, text: str, opts: Dict) -> list:
    parts = ["python3", "-m", "backbone", "run", text]
    for flag, key in (("--cwd", "cwd"), ("--gate", "gate_cmd"), ("--worker", "worker"), ("--project", "project")):
        if opts.get(key):
            parts += [flag, str(opts[key])]
    if opts.get("read_only"):
        parts.append("--read-only")
    pre = f"cd {host.get('dir', '~/agent-router')}"
    if host.get("env"):
        pre += f" && set -a && . {host['env']} && set +a"
    # BACKBONE_SCRUB_PP: __main__ drops PYTHONPATH again so child agents (hermes, pi) do not inherit it
    pp = f"BACKBONE_SCRUB_PP=1 PYTHONPATH={host['pythonpath']} " if host.get("pythonpath") else ""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host["ssh"], f"{pre} && {pp}{shlex.join(parts)}"]


def run(host: Dict, text: str, opts: Dict, runner=subprocess.run, timeout: int = 1800) -> Dict:
    p = runner(build_command(host, text, opts), capture_output=True, text=True, timeout=timeout)
    try:
        out = json.loads(p.stdout[p.stdout.index("{"):])
    except Exception:
        return {"state": "failed", "error": f"remote {host['ssh']}: rc={p.returncode} {(p.stderr or p.stdout)[:300]}"}
    out["host"] = host["ssh"]
    return out
