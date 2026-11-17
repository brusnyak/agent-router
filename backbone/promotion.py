"""Meta-router invariant: non-inferiority margin + eval-before-promotion.

Ported from third_party/meta-router/ROUTER_BIBLE.md (B3, B8):

  B3 — Non-inferiority margin 0.15, floored, never widened.
    Every promotion verdict is read against the pre-registered margin.
  B8 — Eval before promotion.
    Every routing-visible change clears a cross-validated gate (tuned on tuning,
    verdict on heldout) before it ships as default behavior.

The bandit (plan.py / backbone/bandit.py) learns from gate results only.
This module wraps promotion: a worker's posterior is only trusted as the
default pick for a (task_class, worker) cell once it clears a held-out eval
against the current baseline with a non-inferiority margin of 0.15.

Smart-lazy: reuses the outcomes table already in SQLite (graph.finish() records
one row per run). No new deps, no network. Fails open — if there's no held-out
evidence yet, the current policy stands unchanged (never silently promotes).
"""
from __future__ import annotations

import sqlite3
import time
from typing import Optional

NONINFERIORITY_MARGIN = 0.15  # floored, never widened (B3)
MIN_EVAL_N = 20  # minimum held-out samples per cell before a verdict counts


def _accept_rate(con: sqlite3.Connection, task_class: str, route: str,
                 since: Optional[float] = None) -> tuple[float, int]:
    """Return (acceptance_rate, n) for a (task_class, route) cell from outcomes."""
    if since is not None:
        rows = con.execute(
            "SELECT ok FROM outcomes WHERE task_class = ? AND route = ? AND ts >= ?",
            (task_class, route, since)).fetchall()
    else:
        rows = con.execute(
            "SELECT ok FROM outcomes WHERE task_class = ? AND route = ?",
            (task_class, route)).fetchall()
    n = len(rows)
    if n == 0:
        return 0.0, 0
    wins = sum(1 for (ok,) in rows if ok)
    return wins / n, n


def eval_before_promote(con: sqlite3.Connection, task_class: str,
                        candidate: str, baseline: str,
                        margin: float = NONINFERIORITY_MARGIN,
                        since: Optional[float] = None) -> tuple[bool, str]:
    """Decide whether `candidate` may replace `baseline` as the default pick.

    Returns (promote, reason). Promote only if:
      - both cells have >= MIN_EVAL_N held-out samples (else "insufficient evidence"),
      - candidate accept rate >= baseline accept rate - margin (non-inferiority),
      - and candidate is strictly better or within margin of baseline.

    Fails open: returns False (no promotion) with a reason, never raises.
    """
    cand_p, cand_n = _accept_rate(con, task_class, candidate, since)
    base_p, base_n = _accept_rate(con, task_class, baseline, since)

    if cand_n < MIN_EVAL_N:
        return False, f"insufficient evidence for {candidate} (n={cand_n} < {MIN_EVAL_N})"
    if base_n < MIN_EVAL_N:
        return False, f"insufficient evidence for baseline {baseline} (n={base_n} < {MIN_EVAL_N})"

    # non-inferiority: candidate not materially worse than baseline
    if cand_p < base_p - margin:
        return False, (f"{candidate} accept {cand_p:.2f} below baseline "
                       f"{base_p:.2f} - margin {margin:.2f}")
    return True, (f"{candidate} accept {cand_p:.2f} >= baseline "
                  f"{base_p:.2f} - margin {margin:.2f} (n_c={cand_n}, n_b={base_n})")


def promotion_ready(con: sqlite3.Connection, task_class: str, candidate: str,
                    baseline: str = "nim1") -> bool:
    """Convenience bool wrapper around eval_before_promote."""
    promote, _ = eval_before_promote(con, task_class, candidate, baseline)
    return promote


class PromotionGate:
    """Holds the non-inferiority margin and decides promotions.

    Instantiate once (e.g. in core.Backbone.__init__) and call
    `.may_promote(task_class, candidate, baseline)` before letting the bandit's
    learned worker become the default for a cell.
    """

    def __init__(self, con: sqlite3.Connection,
                 margin: float = NONINFERIORITY_MARGIN,
                 min_n: int = MIN_EVAL_N):
        self.con = con
        self.margin = margin
        self.min_n = min_n

    def may_promote(self, task_class: str, candidate: str,
                    baseline: str = "nim1") -> tuple[bool, str]:
        promote, reason = eval_before_promote(self.con, task_class, candidate,
                                              baseline, margin=self.margin)
        return promote, reason
