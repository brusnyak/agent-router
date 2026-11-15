"""SQLite Thompson sampling; only explicit gate results train the posterior."""

import random
import sqlite3

COLD_START_MASS = 10
SAMPLE_CAP = 200  # Hard cap on alpha + beta, including the prior.
BASE_TIER_WEIGHT = {1: 0.3, 2: 0.5, 3: 0.7}
STRENGTH_BONUS = 0.3


class Bandit:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS bandit (
                    cls TEXT NOT NULL, worker TEXT NOT NULL,
                    alpha REAL NOT NULL, beta REAL NOT NULL,
                    latency_ms REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (cls, worker)
                )
            """)

    @staticmethod
    def prior(tier: int, strong: bool) -> tuple[float, float]:
        if tier not in BASE_TIER_WEIGHT:
            raise ValueError("tier must be 1, 2, or 3")
        mean = min(0.95, BASE_TIER_WEIGHT[tier] + STRENGTH_BONUS * strong)
        alpha = mean * COLD_START_MASS
        return alpha, COLD_START_MASS - alpha

    def pick(self, cls, candidates: dict[str, dict], rng=None,
             w_quality=0.7, w_cost=0.3, min_tier=0) -> tuple[str, dict[str, float]]:
        """Initialize eligible cells, then score quality + inverse normalized cost."""
        eligible = {w: c for w, c in candidates.items() if c["tier"] >= min_tier}
        if not eligible:
            raise ValueError("no candidates meet min_tier")
        priors = {}
        for worker, candidate in eligible.items():
            if not 0 <= candidate["cost"] <= 1:
                raise ValueError("cost must be between 0 and 1")
            priors[worker] = self.prior(candidate["tier"], cls in candidate["strengths"])
        sampler = rng if rng is not None else random
        scores = {}
        with self._db:
            for worker, candidate in eligible.items():
                self._db.execute(
                    "INSERT OR IGNORE INTO bandit (cls, worker, alpha, beta) VALUES (?, ?, ?, ?)",
                    (cls, worker, *priors[worker]),
                )
                row = self._db.execute(
                    "SELECT alpha, beta FROM bandit WHERE cls = ? AND worker = ?",
                    (cls, worker),
                ).fetchone()
                quality = sampler.betavariate(row["alpha"], row["beta"])
                scores[worker] = w_quality * quality + w_cost * (1 - candidate["cost"])
        return max(scores, key=scores.get), scores

    def update(self, cls, worker, passed: bool | None, latency_ms=0):
        """Record a gate result; latency is metadata, never a reward signal.

        Call pick first to establish the cell's tier/strength prior.
        Past SAMPLE_CAP both counts are scaled down (recent evidence keeps weight).
        """
        if passed is None:
            return
        if type(passed) is not bool:
            raise TypeError("passed must be True, False, or None")
        with self._db:
            row = self._db.execute("SELECT alpha, beta FROM bandit WHERE cls = ? AND worker = ?", (cls, worker)).fetchone()
            if not row:
                raise KeyError((cls, worker))
            a, b = row["alpha"] + int(passed), row["beta"] + int(not passed)
            if a + b > SAMPLE_CAP:  # decay instead of freezing: LiteLLM drops updates at the cap, which stops adapting forever
                k = SAMPLE_CAP / (a + b)
                a, b = a * k, b * k
            self._db.execute("UPDATE bandit SET alpha = ?, beta = ?, latency_ms = ? WHERE cls = ? AND worker = ?", (a, b, latency_ms, cls, worker))

    def table(self, cls=None) -> list[dict]:
        query = "SELECT * FROM bandit"
        params = () if cls is None else (cls,)
        if cls is not None:
            query += " WHERE cls = ?"
        return [dict(row) for row in self._db.execute(query + " ORDER BY cls, worker", params)]
