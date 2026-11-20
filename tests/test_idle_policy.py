from dataclasses import replace
import math

import pytest

from backbone.idle_policy import Snapshot, decision


READY = Snapshot(idle_seconds=600, on_ac=True, load=2, paused=False)


@pytest.fixture(autouse=True)
def explicit_test_thresholds(monkeypatch):
    monkeypatch.setattr('backbone.idle_policy.load_limits',
                        lambda: {'max_load': 8, 'idle_minutes': 10})


def test_idle_boundary_and_return_to_work():
    assert decision(replace(READY, idle_seconds=599.9)) == 'active'
    assert decision(READY) == 'ready'
    assert decision(replace(READY, idle_seconds=0)) == 'active'


@pytest.mark.parametrize('change, reason', [
    ({'paused': True}, 'paused-or-unknown'),
    ({'paused': None}, 'paused-or-unknown'),
    ({'on_ac': False}, 'power-unavailable'),
    ({'on_ac': None}, 'power-unavailable'),
    ({'load': 8}, 'load-high'),
    ({'load': None}, 'load-unavailable'),
    ({'load': math.nan}, 'load-unavailable'),
    ({'idle_seconds': None}, 'idle-unavailable'),
    ({'idle_seconds': math.inf}, 'idle-unavailable'),
])
def test_safety_checks_fail_closed(change, reason):
    assert decision(replace(READY, **change)) == reason


def test_invalid_policy_rejected():
    with pytest.raises(ValueError):
        decision(READY, min_idle=-1)
