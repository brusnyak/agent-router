"""Mid-task stall detection (ported from litellm-adaptive stall_detector).

Reads a run's recent tool-call steps and reports whether the task looks stuck:
same tool+args repeating, or errors accumulating. No LLM call, no stored state
beyond the steps table; the same window is rescanned per check, so the verdict
follows the conversation rather than latching.

Wired into the router's step log (runs.steps): each `work` step records the
worker's tool signature + ok/error. Call `is_stalled(run_id, n_recent)` before
the lease expires to catch a stuck subagent mid-task, not after reaping.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .runs import Runs


def _tool_signature(kind: str, worker: str, output: str) -> Tuple[str, bool]:
    """Canonicalize a step into (signature, is_error) so the same call compares
    equal across workers (pi, claude, codex, nim-chat all log steps the same way)."""
    sig = f"{worker}:{kind}:{output[:120]}" if output else f"{worker}:{kind}"
    is_error = kind in ("gate", "work") and not output
    return sig, is_error


def is_stalled(runs: Runs, rid: str, recent: int = 6,
               repeat_threshold: int = 3, error_threshold: int = 3) -> Tuple[bool, str]:
    """Whether the newest step is part of a stuck pattern.

    Returns (stalled, reason). Stuck means: the last `recent` steps repeat the
    same signature >= repeat_threshold times, OR >= error_threshold errors in
    the window. Fails open (False) on any error.
    """
    try:
        steps = runs.steps(rid)
    except Exception:
        return False, "could not read steps"
    if not steps:
        return False, "no steps"
    window = steps[-recent:]
    events = [_tool_signature(s.get("kind", ""), s.get("worker", ""), s.get("output") or "")
              for s in window]
    # repetition: same signature appears >= repeat_threshold times
    from collections import Counter
    counts = Counter(sig for sig, _ in events)
    most = counts.most_common(1)
    if most and most[0][1] >= repeat_threshold:
        return True, f"repeated step {most[0][0][:80]} x{most[0][1]}"
    # error accumulation
    n_errors = sum(1 for _, is_err in events if is_err)
    if n_errors >= error_threshold:
        return True, f"{n_errors} errors in last {len(window)} steps"
    return False, "ok"


def detect_stalled_task(runs: Runs, rid: str) -> bool:
    """Backward-compatible single-bool form."""
    stalled, _ = is_stalled(runs, rid)
    return stalled
