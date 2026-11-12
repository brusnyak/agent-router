"""Records task outcomes (success, latency, cost, evidence) in a sqlite3 outcomes table and computes per (task_class, route) statistics, including a Beta(1,1) posterior mean acceptance probability and median latency."""

import sqlite3
import time


class Outcomes:
    """Wrap a sqlite3 connection, persisting task outcomes and reporting per-class/route stats."""

    def __init__(self, con: sqlite3.Connection) -> None:
        self.con = con
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS outcomes ("
            "task_class TEXT, route TEXT, ok INTEGER, latency_ms INTEGER, "
            "cost REAL, evidence_ok INTEGER, ts REAL)"
        )
        self.con.commit()

    def record(self, task_class: str, route: str, ok: bool, latency_ms: int,
               cost: float = 0.0, evidence_ok: bool = True) -> None:
        self.con.execute(
            "INSERT INTO outcomes (task_class, route, ok, latency_ms, cost, evidence_ok, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_class, route, int(ok), int(latency_ms), float(cost), int(evidence_ok), time.time()),
        )
        self.con.commit()

    def stats(self, task_class: str, route: str) -> dict:
        rows = self.con.execute(
            "SELECT ok, latency_ms FROM outcomes WHERE task_class = ? AND route = ?",
            (task_class, route),
        ).fetchall()
        n = len(rows)
        wins = sum(1 for ok, _ in rows if ok)
        p_accept = (wins + 1) / (n + 2)
        if n == 0:
            median_latency_ms = 0
        else:
            latencies = sorted(ms for _, ms in rows)
            mid = n // 2
            if n % 2 == 1:
                median_latency_ms = latencies[mid]
            else:
                median_latency_ms = int((latencies[mid - 1] + latencies[mid]) / 2)
        return {
            "n": n,
            "wins": wins,
            "p_accept": p_accept,
            "median_latency_ms": int(median_latency_ms),
        }
