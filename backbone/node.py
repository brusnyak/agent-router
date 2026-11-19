"""Node client: connects OUTBOUND to a hub's `serve` API, claims jobs addressed to this node, runs them locally, posts results.
No inbound port on this machine. Gates and cwd are re-resolved against THIS machine's config, never taken as commands from the hub."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable, Optional


def _post(hub: str, token: str, path: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(hub.rstrip("/") + path, json.dumps(payload).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def local_opts(bb, opts: dict) -> dict:
    """Keep only options this node can verify itself."""
    out = {}
    if opts.get("gate_name"):
        out["gate"] = bb.named_gate(opts["gate_name"])
    if opts.get("cwd"):
        out["cwd"] = bb.check_cwd(opts["cwd"])
    for k in ("project", "worker", "read_only"):
        if opts.get(k):
            out[k] = opts[k]
    for k in ('prepared', 'use_vault', 'escalate'):
        if k in opts:
            out[k] = opts[k]
    if os.environ.get("NODE_ALLOW_WRITE") != "1":  # default: a hub job can never write on this machine
        out["read_only"] = True
    return out


def poll_once(bb, hub: str, token: str, name: str, caps: dict, runner: Optional[Callable] = None) -> bool:
    """Claim at most one job, run it, report. Returns True if a job was handled."""
    job = _post(hub, token, "/nodes/claim", {"node": name, "caps": caps}).get("job")
    if not job:
        return False
    run = runner or (lambda text, **o: bb.run(text, **o))
    try:
        res = run(job["text"], **local_opts(bb, job.get("opts", {})))
        state, out, rid = ("done" if res.get("state") == "done" else "blocked"), str(res.get("output") or res.get("error") or ""), res.get("run", "")
    except Exception as e:  # report instead of leaving the job 'running' forever
        state, out, rid = "blocked", f"node error: {type(e).__name__}: {e}", ""
    _post(hub, token, "/nodes/result", {"node": name, "job": job["id"], "state": state, "output": out, "run": rid})
    return True


def loop(bb, hub: str, name: str, poll_s: float = 3.0) -> None:
    token = os.environ.get("BACKBONE_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("set BACKBONE_TOKEN (>=16 chars, same as the hub)")
    root = os.path.expanduser("~/.agent-router")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "router-node.pid"), "w") as f:
        f.write(str(os.getpid()))
    caps = {"workers": sorted(bb.allowed()["workers"]), "host": os.uname().nodename.split(".")[0]}
    while True:
        try:
            if os.uname().sysname == 'Darwin':
                from .idle_policy import current_snapshot, decision
                caps['idle_state'] = decision(current_snapshot())
            busy = poll_once(bb, hub, token, name, caps)
        except Exception:
            busy = False
            time.sleep(10)  # hub unreachable: retry quietly, jobs stay queued on the hub
        time.sleep(0 if busy else poll_s)
