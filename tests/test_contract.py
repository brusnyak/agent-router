import json
import shlex
import socket
import subprocess
import sys
import time
from dataclasses import asdict
from unittest.mock import Mock

import pytest

from backbone.contract import Outcome, TaskContract, main, run_contract, validate


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ROUTER_HOME", str(tmp_path / "router"))
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))


def command(code):
    return shlex.join([sys.executable, "-c", code])


def contract(tmp_path, **kwargs):
    return TaskContract(goal="Build the artifact", worker="fake", cwd=str(tmp_path),
                        retry_backoff_s=0, **kwargs)


def success(*args, **kwargs):
    return {"state": "done", "output": "worker output"}


def test_pass_and_router_owned_acceptance(tmp_path):
    c = contract(tmp_path, acceptance=[command("from pathlib import Path; assert Path('artifact').read_text() == 'ok'")])
    def runner(prompt, **kwargs):
        assert prompt == c.goal
        assert kwargs["gate"] is None
        assert kwargs["escalate"] == ""
        (tmp_path / "artifact").write_text("ok")
        return success()
    result = run_contract(c, runner)
    assert result["outcome"] == Outcome.PASS
    assert result["attempts"][0]["ok"]
    assert result["attempts"][0]["acceptance"][0]["rc"] == 0
    saved = json.loads((tmp_path / "router/data/outcomes.jsonl").read_text())
    assert saved == result


def test_acceptance_retry_contains_failure_tail(tmp_path):
    prompts = []
    def runner(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 3:
            (tmp_path / "artifact").touch()
        return success()
    c = contract(tmp_path, acceptance=[command("from pathlib import Path; print('missing artifact'); assert Path('artifact').exists()")])
    result = run_contract(c, runner)
    assert result["outcome"] == "PASS"
    assert len(result["attempts"]) == 3
    assert "missing artifact" in prompts[1]


def test_acceptance_never_passes_and_runs_all_checks(tmp_path):
    c = contract(tmp_path, acceptance=[command("raise SystemExit(3)"), command("print('checked')")])
    result = run_contract(c, success)
    assert result["outcome"] == "FAIL_ACCEPTANCE"
    assert len(result["attempts"]) == 3
    assert [a["rc"] for a in result["attempts"][0]["acceptance"]] == [3, 0]


def test_worker_raises_retries(tmp_path):
    runner = Mock(side_effect=RuntimeError("transient"))
    result = run_contract(contract(tmp_path), runner)
    assert result["outcome"] == "FAIL_TRANSIENT"
    assert "transient" in result["reason"]
    assert runner.call_count == 3


def test_worker_failed_state_is_not_success(tmp_path):
    runner = Mock(return_value={"state": "blocked", "output": "claims success"})
    result = run_contract(contract(tmp_path), runner)
    assert result["outcome"] == "CRASH"
    assert runner.call_count == 3


def test_wall_budget_interrupts_worker(tmp_path):
    def runner(*args, **kwargs):
        time.sleep(2)
        return success()
    result = run_contract(contract(tmp_path, budget={"max_wall_s": 1}), runner)
    assert result["outcome"] == "BUDGET_EXHAUSTED"
    assert len(result["attempts"]) == 1


def test_timeout_is_distinct_from_wall_budget(tmp_path):
    def runner(*args, **kwargs):
        try:
            time.sleep(2)
            return success()
        except Exception:
            return success()  # Backbone also catches Exception internally.
    result = run_contract(contract(tmp_path, timeout_s=1, max_retries=0), runner)
    assert result["outcome"] == "TIMEOUT"


@pytest.mark.parametrize("budget", [{"max_attempts": 0}, {"max_wall_s": 0}])
def test_empty_budget_never_dispatches(tmp_path, budget):
    runner = Mock()
    assert run_contract(contract(tmp_path, budget=budget), runner)["outcome"] == "BUDGET_EXHAUSTED"
    runner.assert_not_called()


def test_attempt_budget_and_retry_backoff(tmp_path, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("backbone.contract.time.sleep", sleep)
    c = contract(tmp_path, max_retries=3, budget={"max_attempts": 2})
    c.retry_backoff_s = 0.5
    result = run_contract(c, Mock(return_value={"ok": False}))
    assert result["outcome"] == "BUDGET_EXHAUSTED"
    assert len(result["attempts"]) == 2
    sleep.assert_called_once_with(0.5)


def test_backoff_cannot_exceed_wall_budget(tmp_path):
    c = contract(tmp_path, budget={"max_wall_s": 1})
    c.retry_backoff_s = 2
    result = run_contract(c, Mock(side_effect=RuntimeError("retry")))
    assert result["outcome"] == "BUDGET_EXHAUSTED"
    assert len(result["attempts"]) == 1


def test_owner_approval_never_dispatches(tmp_path):
    runner = Mock()
    result = run_contract(contract(tmp_path, owner_approval=True), runner)
    assert result["outcome"] == "NEEDS_OWNER"
    assert result["attempts"] == []
    runner.assert_not_called()


def test_idempotency_and_every_final_outcome_saved(tmp_path):
    c = contract(tmp_path, idempotency_key="same-task")
    first = run_contract(c, success)
    runner = Mock()
    result = run_contract(c, runner)
    assert result["outcome"] == "RACE_LOST"
    assert result["attempts"] == []
    runner.assert_not_called()
    assert len((tmp_path / "router/data/outcomes.jsonl").read_text().splitlines()) == 1


def test_failed_outcome_is_not_idempotent_hit(tmp_path):
    c = contract(tmp_path, idempotency_key="same-task", max_retries=0)
    run_contract(c, Mock(side_effect=RuntimeError("failed")))
    assert run_contract(c, success)["outcome"] == "PASS"


@pytest.mark.parametrize("change", [
    {"unknown": True}, {"goal": ""}, {"worker": None}, {"timeout_s": 0},
    {"timeout_s": 3601}, {"timeout_s": True}, {"max_retries": 6},
    {"max_retries": -1}, {"acceptance": "true"}, {"acceptance": [""]},
    {"acceptance": [1]}, {"budget": {"unknown": 1}}, {"budget": []},
    {"budget": {"max_attempts": -1}}, {"budget": {"max_wall_s": True}},
    {"retry_backoff_s": float("nan")}, {"retry_backoff_s": -1}, {"cwd": 7},
    {"owner_approval": "yes"},
])
def test_invalid_contract(tmp_path, change):
    d = {**asdict(contract(tmp_path)), **change}
    assert not validate(d)[0]
    runner = Mock()
    assert run_contract(d, runner)["outcome"] == "INVALID_CONTRACT"
    runner.assert_not_called()


def test_json_validation_and_defaults():
    assert validate('{"goal":"task","worker":"fake"}') == (True, [])
    assert not validate("{")[0]
    assert not validate([])[0]
    assert not validate({})[0]
    assert len(TaskContract("g", "w").id) == 8
    assert TaskContract("g", "w").id != TaskContract("g", "w").id


@pytest.mark.parametrize("size", [0, 10])
def test_output_truncation(tmp_path, size):
    c = contract(tmp_path, budget={"max_output_chars": size},
                 acceptance=[command("print('z' * 100)")])
    result = run_contract(c, Mock(return_value={"ok": True, "output": "x" * 100}))
    assert result["outcome"] == "PASS"
    assert result["output"] == "x" * size
    assert len(result["attempts"][0]["acceptance"][0]["tail"]) <= size


def test_acceptance_errors_are_failures(tmp_path):
    c = contract(tmp_path, max_retries=0, acceptance=["nonexistent-contract-executable", "'unclosed"])
    result = run_contract(c, success)
    assert result["outcome"] == "FAIL_ACCEPTANCE"
    assert len(result["attempts"][0]["acceptance"]) == 2


def test_acceptance_timeout_budget(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] <= 120
        assert "shell" not in kwargs
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr("backbone.contract.subprocess.run", timeout)
    result = run_contract(contract(tmp_path, max_retries=0, acceptance=["fake"]), success)
    assert result["outcome"] == "FAIL_ACCEPTANCE"
    assert result["attempts"][0]["acceptance"][0]["tail"] == "acceptance timed out"


def test_acceptance_timeout_preserves_tail_for_retry(tmp_path, monkeypatch):
    checks = Mock(side_effect=[subprocess.TimeoutExpired("check", 120, output=b"partial stdout\n",
                                                        stderr=b"failure detail"),
                               subprocess.CompletedProcess("check", 0, "", "")])
    monkeypatch.setattr("backbone.contract.subprocess.run", checks)
    runner = Mock(side_effect=success)
    result = run_contract(contract(tmp_path, acceptance=["check"]), runner)
    assert result["outcome"] == "PASS"
    retry_prompt = runner.call_args_list[1].args[0]
    assert "partial stdout" in retry_prompt and "failure detail" in retry_prompt


def test_acceptance_exhausts_wall_budget_before_next_check(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("backbone.contract.time.monotonic", lambda: clock[0])
    def check(*args, **kwargs):
        assert kwargs["timeout"] == 1
        clock[0] = 2.0
        return subprocess.CompletedProcess(args[0], 0, "", "")
    checks = Mock(side_effect=check)
    monkeypatch.setattr("backbone.contract.subprocess.run", checks)
    result = run_contract(contract(tmp_path, budget={"max_wall_s": 1},
                                   acceptance=["first", "second"]), success)
    assert result["outcome"] == "BUDGET_EXHAUSTED"
    checks.assert_called_once()
    assert len(result["attempts"][0]["acceptance"]) == 1


def test_default_runner_wraps_backbone(tmp_path, monkeypatch):
    from backbone import core
    run = Mock(return_value=success())
    monkeypatch.setattr(core, "Backbone", Mock(return_value=Mock(run=run)))
    assert run_contract(contract(tmp_path))["outcome"] == "PASS"
    assert run.call_args.kwargs["gate"] is None


def test_cli_validate_and_owner_run(tmp_path, capsys):
    from backbone.cli import main as cli_main
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(asdict(contract(tmp_path, owner_approval=True))))
    with pytest.raises(SystemExit) as exc:
        cli_main(["contract", "validate", str(path)])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "PASS"
    with pytest.raises(SystemExit) as exc:
        cli_main(["contract", "run", str(path), "--json"])
    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "NEEDS_OWNER"


def test_cli_malformed_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{")
    assert main(["run", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "INVALID_CONTRACT"
