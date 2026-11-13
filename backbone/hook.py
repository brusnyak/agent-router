"""SHADOW-mode UserPromptSubmit hook core: logs a decision receipt, injects nothing."""
import hashlib
import json
import os
import sys
import threading
import time

MACHINE_PREFIXES = ("Another Claude session sent", "<task-notification")
DEADLINE_S = 0.3


def fnv1a32(s):
    h = 0x811C9DC5
    for b in s.encode("utf-8", "replace"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def _bucket(n):
    return "<200" if n < 200 else "200-599" if n < 600 else "600-1999" if n < 2000 else ">=2000"


def decide(payload, now=time.time, holdout_pct=20):
    prompt = payload.get("prompt") or ""
    sid = payload.get("session_id") or ""
    pid = payload.get("prompt_id") or ""
    ts = now()
    if prompt.startswith(MACHINE_PREFIXES):
        mode, arm, why = "machine-turn", None, "bypass:machine-turn"
    elif os.environ.get("MR_ORCH_DISPATCH"):
        mode, arm, why = "lane-child", None, "bypass:lane-child"
    elif len(prompt) < 6:
        mode, arm, why = "too-short", None, "bypass:too-short"
    else:
        mode, arm, why = "shadow", None, "shadow:no-injection-v0"
    if mode == "shadow" or arm is None:
        if mode == "shadow":
            arm = "none" if not sid else ("holdout" if fnv1a32(sid) % 100 < holdout_pct else "treat")
    return {
        "receipt_id": hashlib.sha256(f"{sid}{pid}{ts}".encode()).hexdigest()[:16],
        "ts": ts,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_len": len(prompt),
        "prompt_len_bucket": _bucket(len(prompt)),
        "mode": mode,
        "arm": arm,
        "selected": [],
        "would_surface": [],  # filled offline by eval/shadow_enrich.py (hook stays LLM- and network-free)
        "abstention": why,
        "session_id": sid,  # ids only, never prompt text: needed by hook_log.join
        "prompt_id": pid,
    }


def main():
    threading.Timer(DEADLINE_S, lambda: os._exit(0)).start()
    try:
        receipt = decide(json.loads(sys.stdin.read()))
        path = os.environ.get("HOOK_LOG") or os.path.expanduser("~/.agent-router/hook-shadow.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(receipt) + "\n")
    except BaseException:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
