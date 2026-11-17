"""Bounded task dispatch with router-owned acceptance and durable outcomes."""
from __future__ import annotations

import argparse
import fcntl
import re
from typing import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import math
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
import tempfile
import uuid


@dataclass
class TaskContract:
    goal: str
    worker: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    project: str = ""
    cwd: str = ""
    timeout_s: int = 600
    max_retries: int = 2
    max_attempts: int = 3
    non_retryable_outcomes: list[str] = field(default_factory=lambda: [
        "FAIL_PERMANENT", "NEEDS_OWNER", "INVALID_CONTRACT"])
    retry_backoff_s: float = 2.0
    budget: dict = field(default_factory=lambda: {
        "max_attempts": 3, "max_wall_s": 1800, "max_output_chars": 20000})
    acceptance: list[str] = field(default_factory=list)
    owner_approval: bool = False
    idempotency_key: str = ""


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL_ACCEPTANCE = "FAIL_ACCEPTANCE"
    FAIL_TRANSIENT = "FAIL_TRANSIENT"
    FAIL_PERMANENT = "FAIL_PERMANENT"
    CRASH = "CRASH"
    RACE_LOST = "RACE_LOST"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    NEEDS_OWNER = "NEEDS_OWNER"
    INVALID_CONTRACT = "INVALID_CONTRACT"



def _handler(outcome, retryable=False, notify=False):
    def decide(contract, attempt=1):
        retry = (retryable and outcome not in contract.non_retryable_outcomes
                 and attempt < min(contract.max_attempts, contract.max_retries + 1,
                                   contract.budget.get("max_attempts", 3)))
        return {"retry": retry,
                "backoff_s": contract.retry_backoff_s * attempt if retry else 0,
                "terminal_state": "done" if outcome in (Outcome.PASS, Outcome.RACE_LOST) else "blocked",
                "notify_owner": notify}
    return decide


HANDLERS: dict[Outcome, Callable] = {
    Outcome.PASS: _handler(Outcome.PASS),
    Outcome.FAIL_TRANSIENT: _handler(Outcome.FAIL_TRANSIENT, True),
    Outcome.FAIL_PERMANENT: _handler(Outcome.FAIL_PERMANENT, notify=True),
    Outcome.FAIL_ACCEPTANCE: _handler(Outcome.FAIL_ACCEPTANCE, True),
    Outcome.TIMEOUT: _handler(Outcome.TIMEOUT, True),
    Outcome.CRASH: _handler(Outcome.CRASH, True),
    Outcome.BUDGET_EXHAUSTED: _handler(Outcome.BUDGET_EXHAUSTED, notify=True),
    Outcome.NEEDS_OWNER: _handler(Outcome.NEEDS_OWNER, notify=True),
    Outcome.INVALID_CONTRACT: _handler(Outcome.INVALID_CONTRACT, notify=True),
    Outcome.RACE_LOST: _handler(Outcome.RACE_LOST),
}


def classify_failure(error):
    text = str(error)
    if isinstance(error, (FileNotFoundError, PermissionError)) or re.search(
            r"\b(?:401|403|127)\b|binary not found|invalid contract|unauthorized|forbidden", text, re.I):
        return Outcome.FAIL_PERMANENT
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)) or re.search(r"timed?\s*out|timeout", text, re.I):
        return Outcome.TIMEOUT
    if isinstance(error, ConnectionError) or re.search(
            r"\b(?:429|5\d\d)\b|connection|ECONN|transient|rate.?limit", text, re.I):
        return Outcome.FAIL_TRANSIENT
    return Outcome.CRASH

def _decode(d):
    return json.loads(d) if isinstance(d, str) else d


def validate(d) -> tuple[bool, list[str]]:
    """Validate a JSON object (or JSON text), including optional budget fields."""
    try:
        d = _decode(d)
    except ValueError as exc:
        return False, [str(exc)]
    if not isinstance(d, dict):
        return False, ["contract must be an object"]
    errors = [f"unknown key: {k}" for k in d if k not in TaskContract.__dataclass_fields__]
    for key in ("goal", "worker"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            errors.append(f"{key} must be a non-empty string")
    for key in ("id", "project", "cwd", "idempotency_key"):
        if key in d and not isinstance(d[key], str):
            errors.append(f"{key} must be a string")
    for key, low, high in (("timeout_s", 1, 3600), ("max_retries", 0, 5), ("max_attempts", 1, 100)):
        if key in d and (type(d[key]) is not int or not low <= d[key] <= high):
            errors.append(f"{key} must be an integer in {low}..{high}")
    if "retry_backoff_s" in d:
        v = d["retry_backoff_s"]
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            errors.append("retry_backoff_s must be finite and non-negative")
    if "owner_approval" in d and type(d["owner_approval"]) is not bool:
        errors.append("owner_approval must be a boolean")
    non_retryable = d.get("non_retryable_outcomes", [])
    if not isinstance(non_retryable, list) or any(o not in Outcome._value2member_map_ for o in non_retryable if isinstance(o, str)) or any(not isinstance(o, str) for o in non_retryable):
        errors.append("non_retryable_outcomes must list valid outcomes")
    a = d.get("acceptance", [])
    if not isinstance(a, list) or any(not isinstance(c, str) or not c.strip() for c in a):
        errors.append("acceptance must be a list of non-empty strings")
    budget = d.get("budget", {})
    defaults = TaskContract("", "").budget
    if not isinstance(budget, dict):
        errors.append("budget must be an object")
    else:
        for key, value in budget.items():
            if key not in defaults:
                errors.append(f"unknown budget key: {key}")
            elif type(value) is not int or value < 0:
                errors.append(f"budget.{key} must be a non-negative integer")
    return not errors, errors


def _ledger() -> Path:
    return Path(os.environ.get("AGENT_ROUTER_HOME", "~/.agent-router")).expanduser() / "data" / "outcomes.jsonl"


def _save(result):
    path = _ledger()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = result.get("idempotency_key")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if key:
        kept = []
        for line in lines:
            try:
                prior = json.loads(line)
            except ValueError:
                kept.append(line)
                continue
            if not isinstance(prior, dict) or prior.get("idempotency_key") != key:
                kept.append(line)
        lines = kept
    lines.append(json.dumps(result))
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".outcomes-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return result


class _WorkerTimeout(BaseException):
    # Backbone catches Exception internally; the deadline must reach this wrapper.
    pass


@contextmanager
def _deadline(seconds):
    """Interrupt synchronous dispatch on POSIX; never leave a retry thread running."""
    def expired(signum, frame):
        raise _WorkerTimeout("worker deadline exceeded")

    previous = signal.signal(signal.SIGALRM, expired)
    timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    started = time.monotonic()
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if timer[0]:
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, timer[0] - (time.monotonic() - started)), timer[1])


def _run(prompt, **kwargs):
    from .core import Backbone
    return Backbone().run(prompt, **kwargs)


def run_contract(contract, runner=None) -> dict:
    path = _ledger().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _run_contract(contract, runner)


def _run_contract(contract, runner=None) -> dict:
    """Run a contract; injected runners accept Backbone.run's call signature."""
    d = asdict(contract) if isinstance(contract, TaskContract) else contract
    ok, errors = validate(d)
    if not ok:
        return _save({"outcome": Outcome.INVALID_CONTRACT.value,
                      "reason": "; ".join(errors), "attempts": []})
    c = TaskContract(**_decode(d))
    budget = {**TaskContract("", "").budget, **c.budget}
    attempts = []
    output = ""

    def finish(outcome, reason):
        return _save({"id": c.id, "idempotency_key": c.idempotency_key,
                      "outcome": outcome.value, "reason": reason,
                      "attempts": attempts, "output": output,
                      **HANDLERS[outcome](c, max(1, len(attempts)))})

    if c.owner_approval:
        return finish(Outcome.NEEDS_OWNER, "owner approval required")
    if c.idempotency_key and _ledger().exists():
        with _ledger().open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    prior = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(prior, dict) and prior.get("idempotency_key") == c.idempotency_key
                        and prior.get("outcome") == Outcome.PASS.value):
                    return {**prior, "outcome": Outcome.RACE_LOST.value, "reason": "idempotent-hit", "attempts": [],
                            **HANDLERS[Outcome.RACE_LOST](c)}

    started = time.monotonic()
    remaining = lambda: budget["max_wall_s"] - (time.monotonic() - started)
    limit = min(c.max_attempts, c.max_retries + 1, budget["max_attempts"])
    prompt = c.goal
    outcome, reason = Outcome.BUDGET_EXHAUSTED, "attempt budget exhausted"
    for n in range(1, limit + 1):
        if remaining() <= 0:
            return finish(Outcome.BUDGET_EXHAUSTED, "wall budget exhausted")
        attempt = {"n": n, "worker": c.worker, "ok": False,
                   "latency_ms": 0, "acceptance": []}
        attempts.append(attempt)
        tick = time.monotonic()
        output = ""
        try:
            with _deadline(min(c.timeout_s, remaining())):
                result = (runner or _run)(prompt, project=c.project, cwd=c.cwd or None,
                                          worker=c.worker, gate=None, escalate="")
            output = str(result.get("output", result.get("text", "")))[:budget["max_output_chars"]]
            worker_ok = result.get("ok", result.get("state") == "done") is True
            reason = str(result.get("error") or output or "worker failed")
            outcome = classify_failure(reason)
        except (_WorkerTimeout, TimeoutError, subprocess.TimeoutExpired) as exc:
            worker_ok = False
            outcome, reason = Outcome.TIMEOUT, str(exc)
        except Exception as exc:
            worker_ok = False
            outcome, reason = classify_failure(exc), f"{type(exc).__name__}: {exc}"
        attempt["latency_ms"] = round((time.monotonic() - tick) * 1000)
        attempt["output"] = output
        if remaining() <= 0:
            return finish(Outcome.BUDGET_EXHAUSTED, "wall budget exhausted")
        if worker_ok:
            for cmd in c.acceptance:
                if remaining() <= 0:
                    return finish(Outcome.BUDGET_EXHAUSTED, "wall budget exhausted")
                try:
                    check = subprocess.run(shlex.split(cmd), cwd=os.path.expanduser(c.cwd) if c.cwd else None,
                                           capture_output=True, text=True, errors="replace",
                                           timeout=min(120, remaining()))
                    rc, tail = check.returncode, check.stdout + check.stderr
                except subprocess.TimeoutExpired as exc:
                    # TimeoutExpired may carry bytes even with text=True.
                    partial = [part.decode(errors="replace") if isinstance(part, bytes) else part or ""
                               for part in (exc.stdout, exc.stderr)]
                    rc, tail = -1, "acceptance timed out\n" + "".join(partial) if any(partial) else "acceptance timed out"
                except (OSError, ValueError) as exc:
                    rc, tail = -1, str(exc)
                attempt["acceptance"].append({"cmd": cmd, "rc": rc,
                                               "tail": tail[-budget["max_output_chars"]:] if budget["max_output_chars"] else ""})
            if remaining() <= 0:
                return finish(Outcome.BUDGET_EXHAUSTED, "wall budget exhausted")
            failures = [a for a in attempt["acceptance"] if a["rc"] != 0]
            if not failures:
                attempt["ok"] = True
                return finish(Outcome.PASS, "all acceptance commands passed")
            outcome, reason = Outcome.FAIL_ACCEPTANCE, "acceptance failed"
            prompt = c.goal + "\n\nRouter acceptance failures:\n" + "\n".join(
                f"{a['cmd']} (rc={a['rc']}): {a['tail']}" for a in failures)
        decision = HANDLERS[outcome](c, n)
        if outcome in c.non_retryable_outcomes or not decision["retry"] and n < limit:
            return finish(outcome, reason)
        if n < limit:
            delay = decision["backoff_s"]
            if delay >= remaining():
                return finish(Outcome.BUDGET_EXHAUSTED, "wall budget insufficient for retry backoff")
            time.sleep(delay)
    if limit < c.max_retries + 1:
        return finish(Outcome.BUDGET_EXHAUSTED, "attempt budget exhausted")
    return finish(outcome, reason)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="backbone contract")
    parser.add_argument("action", choices=("validate", "run"))
    parser.add_argument("file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        d = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result = {"outcome": Outcome.INVALID_CONTRACT.value, "reason": str(exc), "attempts": []}
        if args.action == "run":
            _save(result)
    else:
        if args.action == "run":
            result = run_contract(d)
        else:
            ok, errors = validate(d)
            result = {"outcome": Outcome.PASS.value if ok else Outcome.INVALID_CONTRACT.value,
                      "reason": "valid contract" if ok else "; ".join(errors), "attempts": []}
    print(json.dumps(result))
    return 0 if result["outcome"] == Outcome.PASS.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
