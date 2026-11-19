"""Bounded child supervision primitive; not a scheduler or security sandbox.

Callers must supply an already-authorized handler and a trustworthy snapshot
provider. Do not wire this into unattended dispatch until process-tree, parent
death, locking, isolation, and recovery gates are implemented and tested.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence

from .idle_policy import Snapshot, decision


def supervise(command: Sequence[str], snapshot: Callable[[], Snapshot], *,
              timeout_s: float, poll_s: float = 0.25) -> dict:
    """Start one child only while eligible, killing its group on interruption."""
    if not command or timeout_s <= 0 or poll_s <= 0:
        raise ValueError('command and positive time limits required')
    try:
        initial = decision(snapshot())
    except Exception:
        return {'state': 'probe-error', 'started': False}
    if initial != 'ready':
        return {'state': initial, 'started': False}
    child = subprocess.Popen(list(command), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout_s
    reason = None
    try:
        while child.poll() is None:
            if time.monotonic() >= deadline:
                reason = 'timeout'
                break
            try:
                reason = decision(snapshot())
            except Exception:
                reason = 'probe-error'
            if reason != 'ready':
                break
            reason = None
            time.sleep(min(poll_s, max(0, deadline - time.monotonic())))
        if reason is not None:
            return {'state': reason, 'started': True}
        return {'state': 'completed' if child.returncode == 0 else 'failed',
                'started': True, 'returncode': child.returncode}
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
