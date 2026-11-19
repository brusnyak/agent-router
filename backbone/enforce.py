"""PreToolUse hook for Agent/Task: redirect once, never ban.

A heavy sub-agent call is blocked ONCE with the exact router command to run instead. The same call repeated (or the
phrase ROUTER-OK in it, or a light task, or a cheap model already chosen) goes through. Arms by session hash:
holdout 20% is never touched, so the effect stays measurable. Stdlib only, no network, fails open, 0.3 s deadline."""
import hashlib
import json
import re
import os
import sys
import threading
import time

from .hook import fnv1a32, is_heavy

STATE = os.path.expanduser("~/.agent-router/enforce-state.json")
LOG = os.path.expanduser("~/.agent-router/enforce.jsonl")
CHEAP = ("haiku", "sonnet")  # owner decision 2026-11-15: modern haiku/sonnet are enough; opus/fable add nothing measurable
DEADLINE_S = 0.3
# delegation rules: these routes are Claude-subagent work (browser/MCP/verification/judgment), not NIM-redirectable
ROUTE_TAG = re.compile(r"\broute:\s*(browser|mcp|verify|judgment|private|fresh-context)\b", re.I)


def command_for(prompt: str, picker=None, delegate: bool = False) -> str:
    """Compiled router command. picker(prompt)->dict(worker, gate_hint) comes from plan.py when present."""
    plan = picker(prompt) if picker else {}
    worker = plan.get("worker", "nim1")
    gate = plan.get("gate_hint") or "<gate cmd that exits 0 when the task is done>"
    task = " ".join(prompt.split())[:240].replace("'", "")
    if delegate:
        return f"python3 -m backbone delegate --gate '{gate}' --worker {worker} '{task}'"
    return f"python3 -m backbone run --worker {worker} --gate '{gate}' '{task}'"


def decide(payload: dict, state: dict, now=time.time, picker=None, holdout_pct: int = 20,
           delegate_heavy: bool = False) -> dict:
    """-> {action: allow|block, reason, arm, why}. Mutates state (the one-time block memory).

    When delegate_heavy is True, a heavy task is redirected to `backbone delegate` which
    creates bounded subagents (one per subtask) instead of a single worker.
    """
    ti = payload.get("tool_input") or {}
    prompt = ti.get("prompt") or ti.get("description") or ""
    sid = payload.get("session_id") or ""
    if os.environ.get("MR_ORCH_DISPATCH"):
        return {"action": "allow", "arm": "none", "why": "router-child"}
    arm = "none" if not sid else ("holdout" if fnv1a32(sid) % 100 < holdout_pct else "treat")
    if arm != "treat":
        return {"action": "allow", "arm": arm, "why": "not-treated"}
    if ROUTE_TAG.search(prompt):
        return {"action": "allow", "arm": arm, "why": "route-tag"}
    if "ROUTER-OK" in prompt:
        return {"action": "allow", "arm": arm, "why": "escape-phrase"}
    if any(c in str(ti.get("model", "")).lower() for c in CHEAP):
        return {"action": "allow", "arm": arm, "why": "cheap-model-chosen"}
    if not is_heavy(prompt):
        return {"action": "allow", "arm": arm, "why": "light"}
    key = hashlib.sha256((sid + prompt).encode("utf-8", "replace")).hexdigest()[:16]
    if key in state:
        return {"action": "allow", "arm": arm, "why": "repeat-after-block"}
    state[key] = now()
    cmd = command_for(prompt, picker, delegate=delegate_heavy)
    what = "delegated to bounded subagents (split -> fanout -> gate-checked integration)" if delegate_heavy else "run through the router"
    reason = ("Heavy sub-agent task: " + what + " (isolated worktrees, gate-checked, spreads over NIM keys):\n"
              f"  {cmd}\nIf a built-in sub-agent is truly better, repeat the same call once, or set model to sonnet/haiku, "
              "or add ROUTER-OK to the prompt.")
    return {"action": "block", "arm": arm, "why": "heavy-first-call", "reason": reason}


def _picker():
    try:
        from .plan import quick_pick
        return quick_pick
    except Exception:
        return None


def main():
    threading.Timer(DEADLINE_S, lambda: os._exit(0)).start()
    try:
        payload = json.loads(sys.stdin.read())
        if payload.get("tool_name") not in ("Agent", "Task"):
            os._exit(0)
        try:
            state = json.load(open(STATE))
        except Exception:
            state = {}
        # delegation to bounded subagents is opt-in via config (DECISIONS.md: hooks enforce,
        # but the default stay is a single worker until the owner flips the knob)
        delegate_heavy = False
        try:
            from .core import load_config
            delegate_heavy = bool(load_config().get("delegate", {}).get("heavy", False))
        except Exception:
            pass
        d = decide(payload, state, picker=_picker(), delegate_heavy=delegate_heavy)
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        if d["action"] == "block":
            tmp = STATE + ".tmp"
            json.dump(state, open(tmp, "w"))
            os.replace(tmp, STATE)
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                                "permissionDecisionReason": d["reason"]}}))
            sys.stdout.flush()
        with open(LOG, "a") as f:
            f.write(json.dumps({"ts": time.time(), "sid": payload.get("session_id", ""), "arm": d["arm"], "action": d["action"], "why": d["why"]}) + "\n")
    except BaseException:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
