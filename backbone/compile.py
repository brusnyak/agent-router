"""Dictation -> compact fact card. Deterministic entity pre-pass + optional LLM; always falls back."""
from __future__ import annotations

import itertools
import json
import os
import re
import sys
import urllib.request

COMPILER = (
    "You compile a messy dictation into a task card. Output ONLY one JSON object with keys: "
    "goal (one sentence), task_class (short label), constraints (string), "
    "named_things (list of files, tools, people, systems named verbatim), "
    "open_questions (max 3 items, each {\"q\": question, \"default\": assumed answer}). "
    "Do not invent facts. Keep named things verbatim."
)
def get_base_url():
    try:
        cfg_path = os.path.expanduser("~/.agent-router/backbone.yaml")
        if not os.path.exists(cfg_path):
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "backbone.yaml")
        with open(cfg_path) as _f:
            _cfg = _yaml.safe_load(_f) or {}
        return (_cfg.get("nim", {}) or {}).get("base_url", "https://integrate.api.nvidia.com/v1") + "/chat/completions"
    except Exception:
        return "https://integrate.api.nvidia.com/v1/chat/completions"
# Model loaded from config at runtime - no hard-coded model
import yaml as _yaml
import os as _os
_MODEL_CACHE = None
def get_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = "nvidia/nemotron-3.5-super-vl-120b-a12b"  # sensible default
        try:
            cfg_path = _os.path.expanduser("~/.agent-router/backbone.yaml")
            if not _os.path.exists(cfg_path):
                cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "backbone.yaml")
            with open(cfg_path) as _f:
                _cfg = _yaml.safe_load(_f) or {}
            _MODEL_CACHE = (_cfg.get("nim", {}) or {}).get("model", _MODEL_CACHE)
        except Exception:
            pass
    return _MODEL_CACHE
_PATTERNS = [
    r"https?://[^\s`'\"<>)\]]+",
    r"`([^`\n]+)`",
    r"(?<![\w/])(?:~|\.{1,2})?/[\w.\-~]+(?:/[\w.\-~]+)*",
    r"\b[\w\-]+(?:/[\w.\-]+)+",
    r"\b[\w\-]+\.[A-Za-z][A-Za-z0-9]{0,5}\b",
    r"\b[A-Z][A-Z0-9_]{2,}\b",
    r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b",
    r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b",
]
_rr = itertools.count()


def extract_named(raw: str, known_names=()) -> list:
    hits = []
    for pat in _PATTERNS:
        for m in re.finditer(pat, raw):
            hits.append((m.start(), (m.group(1) if m.groups() else m.group(0)).rstrip(".,;:!?")))
    for n in known_names:
        for m in re.finditer(re.escape(n), raw):
            hits.append((m.start(), n))
    out = []
    for _, t in sorted(hits, key=lambda h: h[0]):
        if t and t not in out:
            out.append(t)
    return out


def _fallback(raw: str, named: list) -> dict:
    goal = re.split(r"(?<=[.!?])\s", raw.strip(), maxsplit=1)[0][:200]
    return {"goal": goal, "task_class": "unknown", "constraints": "", "named_things": named, "open_questions": []}


def _last_json(text: str):
    dec, last, i = json.JSONDecoder(), None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                last = obj
            i = end
        except ValueError:
            i += 1
    return last


def compile_card(raw: str, call=None, known_names=()) -> dict:
    named = extract_named(raw, known_names)
    card = None
    if call:
        try:
            obj = _last_json(call(COMPILER, raw))
            if obj and isinstance(obj.get("goal"), str) and obj["goal"].strip():
                oq = [q for q in (obj.get("open_questions") or []) if isinstance(q, (dict, str))][:3]
                nt = obj.get("named_things")
                card = {"goal": obj["goal"].strip(), "task_class": str(obj.get("task_class") or "unknown"),
                        "constraints": str(obj.get("constraints") or ""),
                        "named_things": [str(x) for x in nt] if isinstance(nt, list) else [],
                        "open_questions": oq}
        except Exception:
            card = None
    if card is None:
        return _fallback(raw, named)
    card["named_things"] += [n for n in named if n not in card["named_things"]]
    return card


def render(card: dict, max_chars: int = 1500) -> str:
    qs = []
    for q in card.get("open_questions") or []:
        qs.append(f"{q.get('q', '')} (default {q.get('default', '')})" if isinstance(q, dict) else str(q))
    parts = [f"Goal: {card.get('goal', '')}", f"Class: {card.get('task_class', '')}",
             f"Constraints: {card.get('constraints', '')}",
             f"Named: {', '.join(card.get('named_things') or [])}", f"Open: {'; '.join(qs)}"]
    s = " | ".join(parts)
    if len(s) <= max_chars:
        return s
    cut = s[:max_chars]
    return cut.rsplit(" ", 1)[0] if " " in cut else cut


def entities_preserved(raw: str, card: dict) -> list:
    text = render(card, max_chars=10**9)
    return [e for e in extract_named(raw) if e not in text]


def nim_call(system: str, user: str) -> str:
    from .keys import env_key_names
    keys = [os.environ[k] for k in env_key_names() if os.environ.get(k)]
    if not keys:
        raise RuntimeError("no NIM keys in env")
    body = {"model": get_model(), "temperature": 0, "max_tokens": 500,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(get_base_url(), json.dumps(body).encode(), {
        "Authorization": "Bearer " + keys[next(_rr) % len(keys)], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    no_llm = "--no-llm" in a
    a = [x for x in a if x != "--no-llm"]
    if not a:
        print('usage: python -m backbone.compile "<raw>" [--no-llm]', file=sys.stderr)
        return 2
    print(render(compile_card(a[0], None if no_llm else nim_call)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
