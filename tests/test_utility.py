from backbone.utility import pick

ROUTES = {"nim1": {"p_accept": 0.60, "cost": 0.0, "latency_ms": 4000},
          "claude": {"p_accept": 0.95, "cost": 0.02, "latency_ms": 9000},
          "or": {"p_accept": 0.50, "cost": 0.0, "latency_ms": 9000},   # dominated by nim1 on every axis
          "codex": {"p_accept": 0.90, "cost": 0.05, "latency_ms": 20000}}


def test_most_accurate_ignores_cost_and_latency():
    assert pick(ROUTES, lam=0.0, mu=0.0)[0] == "claude"


def test_fastest_respects_the_quality_floor():
    assert pick(ROUTES, lam=0.0, mu=1.0, floor=0.7)[0] == "claude"      # nim1 is fastest but below the floor
    assert pick(ROUTES, lam=0.0, mu=1.0, floor=0.0)[0] == "nim1"


def test_dominated_routes_are_dropped_and_explained():
    name, info = pick(ROUTES, lam=1.0, mu=0.0)
    assert "or" in info["dropped"] and name in ("nim1", "claude")


def test_floor_unreachable_falls_back_to_best_accuracy():
    name, info = pick(ROUTES, lam=0.0, mu=1.0, floor=0.99)
    assert name == "claude" and info["reason"] == "no route meets floor"


def test_quota_penalty_moves_choice_away_from_an_exhausted_free_route():
    r = {"a": {"p_accept": 0.7, "cost": 0.0, "latency_ms": 1000, "quota_used": 0.99}, "b": {"p_accept": 0.68, "cost": 0.0, "latency_ms": 1000, "quota_used": 0.1}}
    assert pick(r, lam=0.0, mu=0.0, quota_weight=0.5)[0] == "b"
