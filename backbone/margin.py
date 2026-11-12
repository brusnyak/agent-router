"""Decide whether an LLM should be invoked based on candidate score margins.

needs_llm sorts scores descending and returns True when there are no scores,
when the top score falls below min_top, or when the gap between the top two
scores relative to the top score is smaller than min_margin. Otherwise it
returns False, meaning the top candidate is strong enough to skip the LLM.
"""


def needs_llm(scores, min_margin=0.15, min_top=0.0):
    ordered = sorted(scores, reverse=True)
    if not ordered:
        return True
    top = ordered[0]
    if top < min_top:
        return True
    if len(ordered) >= 2:
        second = ordered[1]
        if (top - second) / max(top, 1e-9) < min_margin:
            return True
    return False
