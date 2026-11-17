"""Generic adapter: vetted local CLI workers, argv-only, no shell."""
import os
from backbone.adapter import GenericWorker, _bounded_env


def test_adapter_blocks_non_allowlisted_command():
    w = GenericWorker("evil", allowlist={"good"}, read_only=True)
    r = w.run("hi", cwd="/tmp")
    assert not r.ok and "not in adapter allowlist" in r.text


def test_adapter_runs_fake_worker_offline(tmp_path, monkeypatch):
    fake = tmp_path / "fakecli"
    fake.write_text("#!/bin/sh\necho \"FAKE-OK:$@\"\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    w = GenericWorker("fakecli", allowlist={"fakecli"}, read_only=True)
    cap = w.probe()
    assert cap.installed and cap.authenticated and not cap.executed
    r = w.run("say hello", cwd=str(tmp_path))
    assert r.ok and r.text == "FAKE-OK:say hello", r.text


def test_adapter_timeout_and_cleanup(monkeypatch):
    w = GenericWorker("sleep", allowlist={"sleep"}, timeout_s=1)
    r = w.run("10", cwd="/tmp")
    assert not r.ok and "timeout" in r.text and r.latency_ms >= 1000


def test_adapter_bounded_env_no_secret_leak(monkeypatch):
    monkeypatch.setenv("NIM_1", "secret-value")
    monkeypatch.setenv("OTHER", "x")
    env = _bounded_env("NIM_")
    assert env.get("NIM_1") == "secret-value" and "OTHER" not in env
    assert env["PATH"] and env["HOME"]
