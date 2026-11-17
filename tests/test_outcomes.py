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


import json
import socket
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from backbone.contract import HANDLERS, Outcome, TaskContract, classify_failure, run_contract, validate


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ROUTER_HOME", str(tmp_path))
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    return tmp_path


def test_handlers_are_exhaustive_and_bounded():
    assert set(HANDLERS) == set(Outcome)
    c = TaskContract("task", "stub")
    assert c.max_attempts == 3
    for outcome in Outcome:
        for attempt in range(1, 5):
            decision = HANDLERS[outcome](c, attempt)
            assert set(decision) == {"retry", "backoff_s", "terminal_state", "notify_owner"}
            assert not decision["retry"] if attempt >= 3 else True
            assert 0 <= decision["backoff_s"] < float("inf")


@pytest.mark.parametrize("error, expected", [
    ("429 rate limited", Outcome.FAIL_TRANSIENT), ("599 server error", Outcome.FAIL_TRANSIENT),
    (ConnectionError("reset"), Outcome.FAIL_TRANSIENT), ("connection refused", Outcome.FAIL_TRANSIENT),
    (TimeoutError(), Outcome.TIMEOUT), ("timed out", Outcome.TIMEOUT),
    (FileNotFoundError(), Outcome.FAIL_PERMANENT), ("401 unauthorized", Outcome.FAIL_PERMANENT),
    ("403 forbidden", Outcome.FAIL_PERMANENT), ("invalid contract", Outcome.FAIL_PERMANENT),
    (RuntimeError("bug"), Outcome.CRASH),
])
def test_classification(error, expected):
    assert classify_failure(error) == expected


@pytest.mark.parametrize("error", ["401", "403", "invalid contract", "worker binary not found"])
def test_permanent_stops_immediately(isolated, error):
    runner = Mock(return_value={"ok": False, "error": error})
    result = run_contract(TaskContract("task", "stub", retry_backoff_s=0), runner)
    assert result["outcome"] == "FAIL_PERMANENT"
    assert runner.call_count == 1


def test_override_and_finite_retries(isolated):
    c = TaskContract("task", "stub", retry_backoff_s=0)
    runner = Mock(side_effect=ConnectionError("reset"))
    result = run_contract(c, runner)
    assert runner.call_count == 3 and result["outcome"] == "FAIL_TRANSIENT"
    c.non_retryable_outcomes.append("FAIL_TRANSIENT")
    runner.reset_mock()
    assert run_contract(c, runner)["outcome"] == "FAIL_TRANSIENT"
    assert runner.call_count == 1


def test_same_key_updates_one_row_even_after_failure(isolated):
    c = TaskContract("task", "stub", idempotency_key="key", max_retries=0)
    run_contract(c, Mock(side_effect=ConnectionError("reset")))
    assert run_contract(c, Mock(return_value={"ok": True}))["outcome"] == "PASS"
    runner = Mock()
    assert run_contract(c, runner)["outcome"] == "RACE_LOST"
    runner.assert_not_called()
    rows = [json.loads(line) for line in (isolated / "data/outcomes.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["outcome"] == "PASS"


@pytest.mark.parametrize("changes", [{"max_attempts": 0}, {"max_attempts": True},
    {"non_retryable_outcomes": ["unknown"]}, {"non_retryable_outcomes": [{}]}])
def test_invalid_retry_policy(changes):
    assert not validate({**asdict(TaskContract("t", "s")), **changes})[0]


def test_concurrent_same_key_dispatches_once(isolated):
    import subprocess
    import sys

    code = '''
from pathlib import Path
import os
import time
from backbone.contract import TaskContract, run_contract
def runner(*args, **kwargs):
    with (Path(os.environ['AGENT_ROUTER_HOME']) / 'calls').open('a') as stream:
        stream.write('dispatch\\n')
    time.sleep(0.05)
    return {'ok': True}
print(run_contract(TaskContract('task', 'stub', idempotency_key='concurrent'), runner)['outcome'])
'''
    processes = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        results = [process.communicate(timeout=10) for process in processes]
        assert all(process.returncode == 0 for process in processes), results
        assert sorted(stdout.strip() for stdout, _ in results) == ["PASS", "RACE_LOST"]
        assert (isolated / "calls").read_text() == "dispatch\n"
        assert len((isolated / "data/outcomes.jsonl").read_text().splitlines()) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
