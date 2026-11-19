import sys

from backbone.idle_policy import Snapshot
from backbone.idle_supervisor import supervise


READY = Snapshot(600, True, 1, False)
ACTIVE = Snapshot(0, True, 1, False)


def test_no_child_when_owner_active(tmp_path):
    marker = tmp_path / 'started'
    command = [sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).touch()']
    assert supervise(command, lambda: ACTIVE, timeout_s=1) == {'state': 'active', 'started': False}
    assert not marker.exists()


def test_child_terminated_when_owner_returns(tmp_path):
    marker = tmp_path / 'late'
    command = [sys.executable, '-c', f'import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()']
    samples = iter([READY, ACTIVE])
    assert supervise(command, lambda: next(samples), timeout_s=2, poll_s=.01) == {'state': 'active', 'started': True}
    assert not marker.exists()


def test_timeout_stops_child():
    result = supervise([sys.executable, '-c', 'import time; time.sleep(5)'],
                       lambda: READY, timeout_s=.1, poll_s=.02)
    assert result == {'state': 'timeout', 'started': True}


def test_success_and_failure_are_distinct():
    assert supervise([sys.executable, '-c', 'pass'], lambda: READY, timeout_s=2)['state'] == 'completed'
    assert supervise([sys.executable, '-c', 'raise SystemExit(7)'], lambda: READY, timeout_s=2)['returncode'] == 7


def test_probe_error_fails_closed():
    def broken():
        raise OSError('probe unavailable')
    assert supervise([sys.executable, '-c', 'pass'], broken, timeout_s=1) == {'state': 'probe-error', 'started': False}


def test_probe_failure_stops_running_child(tmp_path):
    marker = tmp_path / 'late'
    command = [sys.executable, '-c', f'import time; from pathlib import Path; time.sleep(1); Path({str(marker)!r}).touch()']
    calls = iter([READY, None])

    def snapshot():
        value = next(calls)
        if value is None:
            raise OSError('probe unavailable')
        return value

    assert supervise(command, snapshot, timeout_s=2, poll_s=.01) == {'state': 'probe-error', 'started': True}
    assert not marker.exists()
