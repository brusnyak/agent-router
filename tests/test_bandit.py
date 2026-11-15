import random
from collections import Counter

import pytest

from backbone.bandit import Bandit, COLD_START_MASS, SAMPLE_CAP


@pytest.fixture
def bandit(tmp_path):
    instance = Bandit(tmp_path / "bandit.sqlite")
    yield instance
    instance._db.close()


def candidates():
    return {
        "strong": {"tier": 3, "cost": 0.5, "strengths": ["code"]},
        "weak": {"tier": 2, "cost": 0.5, "strengths": []},
    }


def wins(bandit):
    rng = random.Random(42)
    return Counter(bandit.pick("code", candidates(), rng=rng)[0] for _ in range(500))


def test_cold_start_favors_strong_high_tier(bandit):
    counts = wins(bandit)
    assert counts["strong"] > 450
    assert all(row["alpha"] + row["beta"] == COLD_START_MASS for row in bandit.table())


def test_twenty_gate_failures_reverse_preference(bandit):
    bandit.pick("code", candidates())
    for _ in range(20):
        bandit.update("code", "strong", False)
    counts = wins(bandit)
    assert counts["weak"] > counts["strong"]
    assert bandit.table("code")[0]["beta"] == 20.5


def test_none_changes_nothing_even_for_unknown_worker(bandit):
    bandit.update("code", "unknown", None, latency_ms=100)
    assert bandit.table() == []
    bandit.pick("code", candidates())
    before = bandit.table()
    bandit.update("code", "strong", None, latency_ms=999)
    assert bandit.table() == before


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "bandit.sqlite"
    first = Bandit(path)
    first.pick("code", candidates())
    first.update("code", "strong", True, latency_ms=123)
    expected = first.table()
    second = Bandit(path)
    try:
        assert second.table() == expected
        second.update("code", "strong", False)
        row = first.table("code")[0]
        assert (row["alpha"], row["beta"]) == (10.5, 1.5)
    finally:
        first._db.close()
        second._db.close()


@pytest.mark.parametrize("passed", [True, False])
def test_cap_decays_instead_of_freezing(bandit, passed):
    bandit.pick("code", candidates())
    for _ in range(SAMPLE_CAP - COLD_START_MASS):
        bandit.update("code", "strong", passed)
    before = bandit.table()[0]
    assert before["alpha"] + before["beta"] == SAMPLE_CAP
    for _ in range(30):  # evidence flips: the posterior must follow, not stay frozen
        bandit.update("code", "strong", not passed)
    after = bandit.table()[0]
    assert abs(after["alpha"] + after["beta"] - SAMPLE_CAP) < 1e-6
    assert (after["alpha"] > before["alpha"]) == (not passed)


def test_class_isolation_and_filtering(bandit):
    bandit.pick("code", candidates())
    bandit.pick("other", candidates())
    before = bandit.table("other")
    bandit.update("code", "strong", False)
    assert bandit.table("other") == before
    assert len(bandit.table()) == 4
    assert bandit.table("other")[0]["alpha"] == 7


def test_tier_filter_and_empty_candidates(bandit):
    worker, scores = bandit.pick("code", candidates(), min_tier=3)
    assert worker == "strong" and set(scores) == {"strong"}
    assert len(bandit.table()) == 1
    for choices, minimum in [({}, 0), (candidates(), 4)]:
        with pytest.raises(ValueError, match="no candidates"):
            bandit.pick("code", choices, min_tier=minimum)


def test_cost_score_and_prior_validation(bandit):
    choices = candidates()
    choices["strong"]["cost"] = 1
    choices["weak"]["cost"] = 0
    worker, scores = bandit.pick("code", choices, w_quality=0, w_cost=1)
    assert worker == "weak" and scores == {"strong": 0, "weak": 1}
    for tier in (1, 2, 3):
        for strong in (True, False):
            alpha, beta = Bandit.prior(tier, strong)
            assert alpha + beta == COLD_START_MASS
            assert 0 < alpha / COLD_START_MASS <= 0.95
    with pytest.raises(ValueError):
        Bandit.prior(4, False)
    with pytest.raises(TypeError):
        bandit.update("code", "strong", "PASS")
    with pytest.raises(KeyError):
        bandit.update("code", "unknown", True)
