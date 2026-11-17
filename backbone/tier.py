"""Task tier prediction (ported from litellm-adaptive tier_predictor).

Given a prompt, predict which executor tier it needs:
  tier 1 = NIM (free, fast, good for simple/classify/draft)
  tier 2 = claude/codex (paid, stronger, for review/multi_file/complex reasoning)
  tier 3 = expert escalation (codex/claude with larger budget)

Heuristics on code/math/multiple-choice/international/length features — no LLM call,
no training data. Used by plan.py to set min_tier before the Thompson bandit picks
a worker. Falls back to tier 1 on any error (fail open).
"""
from __future__ import annotations

import re

_CODE = re.compile(r"\b(def |class |import |from |function |const |let |-> |=> |\.\w+\()", re.I)
_MATH = re.compile(r"\b(solve|equation|derivative|integral|proof|theorem|calculate|compute|= ?[0-9]+\s*[\+\-\*/])\b", re.I)
_MC = re.compile(r"(?:^|\s)[A-D][.)]\s")
_INTL = re.compile(r"[^\x00-\x7F]")


def _features(prompt: str) -> dict:
    low = prompt.lower()
    return {
        "code": bool(_CODE.search(prompt)),
        "math": bool(_MATH.search(prompt)),
        "multiple_choice": bool(_MC.search(prompt)),
        "international": bool(_INTL.search(prompt)),
        "length": len(prompt),
        "heavy_words": sum(1 for w in ("refactor", "migrate", "implement", "build", "audit", "rewrite",
                                       "every file", "all files", "across the repo", "batch", "overnight")
                           if w in low),
    }


def predict_tier(prompt: str) -> int:
    """Return 1, 2, or 3. Higher tier = stronger (scarcer) worker."""
    f = _features(prompt)
    score = 0
    if f["code"]:
        score += 1
    if f["math"]:
        score += 2
    if f["multiple_choice"]:
        score += 0  # classification, stays tier 1
    if f["international"]:
        score += 1
    if f["length"] > 1500:
        score += 1
    if f["heavy_words"] >= 2:
        score += 2
    if score >= 5:
        return 3
    if score >= 2:
        return 2
    return 1
