"""UserPromptSubmit hook core: logs a decision receipt and, for the treat arm,
injects a compact skill body as factual additionalContext so skills actually
surface to the model.

Shadow-only invariant preserved: the hook imports no LLM client, does no
network, and prints nothing unless a skill is selected. Injection is
deterministic (BM25 over an exported library index, score floor), holdout gets
nothing, and everything fails open if the index is absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
from typing import List, Optional

try:                                    # works as `python -m backbone.hook` and as the script `backbone/hook.py`
    from .pick import pick
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from backbone.pick import pick

MACHINE_PREFIXES = ("Another Claude session sent", "<task-notification")
DEADLINE_S = 0.3
INDEX_PATH = os.path.expanduser("~/.agent-router/library-index.jsonl")
SCORE_FLOOR = 0.02
MAX_BODIES = 1
MAX_CHARS = 1200


def fnv1a32(s):
    h = 0x811C9DC5
    for b in s.encode("utf-8", "replace"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def _bucket(n):
    return "<200" if n < 200 else "200-599" if n < 600 else "600-1999" if n < 2000 else ">=2000"


HEAVY = ("refactor", "migrate", "implement", "build ", "audit", "rewrite", "write tests", "test suite",
         "every file", "all files", "across the repo", "scrape", "batch", "overnight", "for each",
         "compare all", "summarize all", "research ", "analy")


def _fts_query(q: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", q.lower())][:12]
    return " OR ".join(f'"{w}"' for w in words)


def _score(hit_terms: List[str], query_terms: List[str]) -> float:
    if not query_terms:
        return 0.0
    hits = set(hit_terms)
    return sum(1 for t in query_terms if t in hits) / len(query_terms)


def _load_index() -> List[dict]:
    rows: List[dict] = []
    try:
        with open(INDEX_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except (OSError, ValueError):
        pass
    return rows


def _retrieve(index: List[dict], prompt: str, k: int = 5) -> List[dict]:
    terms = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", prompt.lower())]
    scored = []
    for row in index:
        haystack = " ".join(
            str(row.get(f, "")) for f in ("name", "description", "body")
        ).lower()
        hay_terms = set(re.findall(r"[A-Za-z0-9_]{3,}", haystack))
        score = _score(list(hay_terms), terms)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]


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
        mode, arm, why = "shadow", None, "shadow:inject-v1"
    if mode == "shadow" or arm is None:
        if mode == "shadow":
            arm = "none" if not sid else ("holdout" if fnv1a32(sid) % 100 < holdout_pct else "treat")

    would_surface: List[str] = []
    selected: List[str] = []
    additional: Optional[str] = None

    # Deterministic pre-injection: treat arm only, score floor, factual body.
    if arm == "treat" and mode == "shadow":
        index = _load_index()
        got = pick(index, prompt) if index else None
        if got:
            h, _, _why = got
            name = h.get("name") or h.get("id") or "skill"
            kind = h.get("kind") or "skill"
            if kind == "skill":    # skills are method: inject the head of the body
                body = (h.get("body") or "").strip()[:MAX_CHARS]
                additional = f"### Possibly relevant skill '{name}' (advisory; apply only if it fits the request)\n{body}"
            else:                  # personas and commands are pointers, never loaded into the prompt
                what = {"command": "slash command /", "agent": "specialist persona ", "subagent": "subagent type "}.get(kind, kind + " ")
                additional = (f"Possibly relevant {what}{name}: {(h.get('description') or '')[:160]}"
                              + (f" (file: {h['source']})" if h.get("source") else "") + ". Advisory; use only if it fits.")
            would_surface = [name]
            selected = ["skill-inject"]

    return {
        "receipt_id": hashlib.sha256(f"{sid}{pid}{ts}".encode()).hexdigest()[:16],
        "ts": ts,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_len": len(prompt),
        "prompt_len_bucket": _bucket(len(prompt)),
        "mode": mode,
        "arm": arm,
        "selected": selected,
        "would_surface": would_surface,
        "additional_context": additional,  # None unless a skill clears the floor
        "abstention": why,
        "session_id": sid,
        "prompt_id": pid,
    }


def main():
    threading.Timer(DEADLINE_S, lambda: os._exit(0)).start()
    try:
        receipt = decide(json.loads(sys.stdin.read()))
        additional = receipt.get("additional_context")
        if additional:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional,
                }
            }
            sys.stdout.write(json.dumps(out))
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
