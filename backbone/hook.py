"""UserPromptSubmit hook core: logs a decision receipt. Injects only a short delegation nudge for heavy prompts in the treat arm (80%); the 20% holdout and all other prompts get nothing, so the A/B stays measurable."""
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


HEAVY = ("refactor", "migrate", "implement", "build ", "audit", "rewrite", "write tests", "test suite", "every file", "all files", "across the repo",
         "scrape", "batch", "overnight", "for each", "compare all", "summarize all", "research ", "analy")
NUDGE = ("[router] Heavy task? Delegate bounded, gate-checkable pieces instead of doing them inline: "
         "`python3 -m backbone run --worker <w> --gate '<cmd>' '<task>'` (isolated worktree, returns a patch for review); "
         "workers: nim1|nim2|nim3 (free NVIDIA NIM keys), omp, opencode (3 models via NIM proxy), cline, codex (build/verify), claude (judgment/browser/MCP); "
         "`backbone discover` lists what is installed, `backbone doctor` probes it. "
         "`backbone fanout` for parallel read/summarise jobs; prefix `@host:oracle-vm` for unattended or standalone work. Light edits stay inline.")


def is_heavy(prompt):
    p = prompt.lower()
    return len(prompt) >= 900 or sum(1 for k in HEAVY if k in p) >= 2


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
    selected = ["heavy-nudge"] if arm == "treat" and mode == "shadow" and is_heavy(prompt) else []
    return {
        "receipt_id": hashlib.sha256(f"{sid}{pid}{ts}".encode()).hexdigest()[:16],
        "ts": ts,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_len": len(prompt),
        "prompt_len_bucket": _bucket(len(prompt)),
        "mode": mode,
        "arm": arm,
        "selected": selected,
        "would_surface": [],  # filled offline by eval/shadow_enrich.py (hook stays LLM- and network-free)
        "abstention": why,
        "session_id": sid,  # ids only, never prompt text: needed by hook_log.join
        "prompt_id": pid,
    }


def main():
    threading.Timer(DEADLINE_S, lambda: os._exit(0)).start()
    try:
        receipt = decide(json.loads(sys.stdin.read()))
        if receipt["selected"]:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": NUDGE}}))
            sys.stdout.flush()
        path = os.environ.get("HOOK_LOG") or os.path.expanduser("~/.agent-router/hook-shadow.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(receipt) + "\n")
    except BaseException:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
