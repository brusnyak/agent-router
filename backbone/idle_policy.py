"""Fail-closed eligibility for an unattended idle-mode controller.

This module only decides eligibility. It does not start jobs or change state.
The supervisor must recheck while a child is running and terminate it on loss
of eligibility; a one-time check is not an enforcement boundary.
"""
from dataclasses import dataclass
import math

from .limits import load_limits


@dataclass(frozen=True)
class Snapshot:
    idle_seconds: float | None
    on_ac: bool | None
    load: float | None
    paused: bool | None


def decision(snapshot: Snapshot, *, min_idle: float | None = None, max_load: float | None = None) -> str:
    """Return 'ready' or the first reason the supervisor must not run."""
    if min_idle is None or max_load is None:
        limits = load_limits()
        min_idle = limits['idle_minutes'] * 60 if min_idle is None else min_idle
        max_load = limits['max_load'] if max_load is None else max_load
    if not math.isfinite(min_idle) or min_idle < 0 or not math.isfinite(max_load) or max_load <= 0:
        raise ValueError('invalid policy thresholds')
    if snapshot.paused is not False:
        return 'paused-or-unknown'
    if snapshot.on_ac is not True:
        return 'power-unavailable'
    if snapshot.load is None or not math.isfinite(snapshot.load) or snapshot.load < 0:
        return 'load-unavailable'
    if snapshot.load >= max_load:
        return 'load-high'
    if snapshot.idle_seconds is None or not math.isfinite(snapshot.idle_seconds) or snapshot.idle_seconds < 0:
        return 'idle-unavailable'
    if snapshot.idle_seconds < min_idle:
        return 'active'
    return 'ready'


def current_snapshot() -> Snapshot:
    """Read the existing macOS probes; failures are unknown and fail closed."""
    from . import bracket, guard
    try:
        idle = bracket.idle_seconds()
    except (OSError, ValueError):
        idle = None
    try:
        ac = bracket.ac_power()
    except (OSError, ValueError):
        ac = None
    try:
        import os
        load = os.getloadavg()[0]
    except OSError:
        load = None
    try:
        paused = bool(guard.paused())
    except OSError:
        paused = None
    return Snapshot(idle_seconds=idle, on_ac=ac, load=load, paused=paused)


if __name__ == '__main__':
    import dataclasses
    import json
    snapshot = current_snapshot()
    print(json.dumps({'state': decision(snapshot), 'snapshot': dataclasses.asdict(snapshot)}))
