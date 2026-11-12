"""Route selection utility for the backbone layer.

pick(routes, lam, mu, floor=0.0, quota_weight=0.0) chooses a single route name
from a name -> dict mapping of routes (keys p_accept, cost, latency_ms, and
optionally quota_used in 0..1). It works in three steps: (1) drop Pareto-dominated
routes — a route is dropped when another route has p_accept >=, cost <=, and
latency_ms <= with at least one strict inequality, recorded in info["dropped"];
(2) keep only routes with p_accept >= floor, falling back to the max p_accept
route among all routes with info["reason"] = "no route meets floor" when none
qualify; (3) score each remaining route as p_accept - lam*cost - mu*(latency_ms/1000/10)
- quota_weight*quota_used and pick the max score, breaking ties by higher
p_accept then by name. info carries reason ("best score" by default), a scores
dict, and the dropped list.
"""

__all__ = ["pick"]


def _dominates(other, route):
    return (
        other["p_accept"] >= route["p_accept"]
        and other["cost"] <= route["cost"]
        and other["latency_ms"] <= route["latency_ms"]
        and (
            other["cost"] < route["cost"]
            or other["latency_ms"] < route["latency_ms"]
        )
    )


def pick(routes, lam, mu, floor=0.0, quota_weight=0.0):
    names = list(routes)

    dropped = []
    for name in names:
        route = routes[name]
        for other_name in names:
            if other_name == name:
                continue
            if _dominates(routes[other_name], route):
                dropped.append(name)
                break

    kept = [n for n in names if n not in dropped]

    def score(n):
        r = routes[n]
        return (
            r["p_accept"]
            - lam * r["cost"]
            - mu * (r["latency_ms"] / 1000 / 10)
            - quota_weight * r.get("quota_used", 0.0)
        )

    qualified = [n for n in kept if routes[n]["p_accept"] >= floor]

    if qualified:
        candidates = qualified
        reason = "best score"
        key = lambda n: (-score(n), -routes[n]["p_accept"], n)
    else:
        candidates = names
        reason = "no route meets floor"
        key = lambda n: (-routes[n]["p_accept"], n)

    best = min(candidates, key=key)

    info = {
        "reason": reason,
        "scores": {n: score(n) for n in names},
        "dropped": dropped,
    }
    return best, info
