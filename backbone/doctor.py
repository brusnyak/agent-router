"""Doctor: does each agent on this machine actually run headless right now? One tiny probe per agent, in parallel.
Writes capabilities.json next to the DB. A binary on PATH is not the same as a usable worker."""
from __future__ import annotations

import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from .workspace import run_group

PROBE = "Reply with the single word: ok"
PROBES = {
    "claude": lambda b: [b, "-p", PROBE, "--output-format", "text", "--no-session-persistence", "--setting-sources", "project", "--permission-mode", "plan"],
    "codex": lambda b: [b, "exec", "--ephemeral", "-s", "read-only", "--skip-git-repo-check", PROBE],
    "qwen": lambda b: [b, "-p", PROBE],
    "kilo": lambda b: [b, "run", "--auto", PROBE],
    "opencode": lambda b: [b, "run", PROBE],
    "omp": lambda b: [b, "-p", "--no-session", PROBE],
    "pi": lambda b: [b, "-p", "--no-session", "--no-extensions", "--no-mcp", "--no-skills", "--model", "nvidia/nemotron-3.5-super-vl-120b-a12b", "--", PROBE],  # same route as PiWorker (NVIDIA key from the pool)
}


def probe(name: str, binary: str, cwd: str, timeout: int = 60) -> Dict:
    t0 = time.time()
    build = PROBES.get(name)
    if not build:
        return {"name": name, "path": binary, "usable": None, "note": "no probe defined"}
    try:
        env = os.environ.copy()
        if name == "pi" and not env.get("NVIDIA_API_KEY"):
            from .keys import load_named
            env["NVIDIA_API_KEY"] = load_named(["NIM_1"]).get("NIM_1", "")
        p = run_group(build(binary), cwd=cwd, timeout=timeout, env=env)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        ok = p.returncode == 0 and "ok" in out.lower()
        return {"name": name, "path": binary, "usable": ok, "latency_s": round(time.time() - t0, 1),
                "note": "" if ok else out[:200].replace("\n", " ")}
    except Exception as e:
        return {"name": name, "path": binary, "usable": False, "latency_s": round(time.time() - t0, 1),
                "note": f"{type(e).__name__}: {str(e)[:120]}"}


def run(agents: Dict[str, str], cwd: str, out_path: Optional[str] = None, only: Optional[List[str]] = None) -> Dict:
    todo = {k: v for k, v in agents.items() if not only or k in only}
    with ThreadPoolExecutor(max_workers=max(1, len(todo))) as ex:
        rows = list(ex.map(lambda kv: probe(kv[0], kv[1], cwd), todo.items()))
    browser = {"ego-browser": bool(shutil.which("ego-browser"))}
    res = {"checked": time.strftime("%Y-%m-%dT%H:%M:%S"), "agents": rows, "browsers_cli": browser}
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        json.dump(res, open(out_path, "w"), indent=2)
    return res
