import sqlite3
from backbone.outcomes import Outcomes


def test_record_and_stats_with_beta_prior():
    o = Outcomes(sqlite3.connect(":memory:"))
    for ok, ms in ((True, 100), (True, 300), (False, 200), (True, 200)):
        o.record("review", "nim1", ok, ms, cost=0.0)
    s = o.stats("review", "nim1")
    assert s["n"] == 4 and s["wins"] == 3
    assert abs(s["p_accept"] - 4 / 6) < 1e-9  # (wins+1)/(n+2)
    assert s["median_latency_ms"] == 200


def test_unknown_route_returns_the_prior_not_an_error():
    s = Outcomes(sqlite3.connect(":memory:")).stats("plan", "claude")
    assert s == {"n": 0, "wins": 0, "p_accept": 0.5, "median_latency_ms": 0}


def test_stats_are_per_class_and_route():
    o = Outcomes(sqlite3.connect(":memory:"))
    o.record("review", "nim1", True, 10); o.record("plan", "nim1", False, 10); o.record("review", "codex", False, 10)
    assert o.stats("review", "nim1")["n"] == 1 and o.stats("plan", "nim1")["wins"] == 0 and o.stats("review", "codex")["wins"] == 0
