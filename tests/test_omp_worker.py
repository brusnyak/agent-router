import json
import os
import socket
import sys
from types import SimpleNamespace

import pytest

from backbone import discover, doctor, otel
from backbone.core import Backbone, norm_worker, parse
from backbone.workers import OmpWorker


@pytest.fixture(autouse=True)
def no_telemetry(monkeypatch):
    monkeypatch.setattr(otel, "_TRACER", False)

    def forbid_network(*args, **kwargs):
        pytest.fail("network forbidden in omp worker tests")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)


@pytest.fixture
def fake_omp(tmp_path, monkeypatch):
    binary = tmp_path / "omp"
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))

    def install(body):
        binary.write_text(f"#!{sys.executable}\n" + body + "\n")
        binary.chmod(0o755)

    return install


def test_success_cwd_arguments_and_model(fake_omp, tmp_path):
    fake_omp("import json, os, sys\nprint(json.dumps([sys.argv[1:], os.getcwd()]))")
    prompt = 'inspect "quoted" text; $(no-shell)'
    result = OmpWorker({"model": "provider/model"}).run(prompt, str(tmp_path))
    assert result.ok and result.worker == "omp"
    assert json.loads(result.text) == [
        ["-p", "--no-session", "--model", "provider/model", prompt], str(tmp_path)
    ]
    assert result.latency_ms >= 0


@pytest.mark.parametrize("output", ["Working...\nanswer", "Working... loading\n\nanswer"])
def test_progress_stripped(fake_omp, tmp_path, output):
    fake_omp(f"print({output!r})")
    result = OmpWorker({}).run("task", str(tmp_path))
    assert result.ok and result.text == "answer"


def test_nonleading_progress_preserved(fake_omp, tmp_path):
    fake_omp("print('answer\\nWorking...')")
    assert OmpWorker({}).run("task", str(tmp_path)).text == "answer\nWorking..."


def test_nonzero_exit_returns_stderr_tail(fake_omp, tmp_path):
    fake_omp("import sys\nprint('partial')\nprint('x' * 500 + 'error tail', file=sys.stderr)\nsys.exit(7)")
    result = OmpWorker({}).run("task", str(tmp_path))
    assert not result.ok and len(result.text) == 400
    assert result.text.endswith("error tail")


@pytest.mark.parametrize("output", ["", "   ", "Working...\n"])
def test_empty_output_failed(fake_omp, tmp_path, output):
    fake_omp(f"import sys\nprint({output!r})\nprint('empty diagnostic', file=sys.stderr)")
    result = OmpWorker({}).run("task", str(tmp_path))
    assert not result.ok and result.text == "empty diagnostic"


def test_timeout_returns_failure(fake_omp, tmp_path):
    fake_omp("import time\ntime.sleep(30)")
    result = OmpWorker({"timeout_s": 1}).run("task", str(tmp_path))
    assert not result.ok and "timeout after 1s" in result.text
    assert result.latency_ms == 1000


@pytest.mark.parametrize("read_only", [False, True])
def test_read_only_prompt_suffix(fake_omp, tmp_path, read_only):
    fake_omp("import json, sys\nprint(json.dumps(sys.argv[1:]))")
    result = OmpWorker({}).run("task", str(tmp_path), read_only=read_only)
    suffix = "\nREAD-ONLY: do not edit or create files" if read_only else ""
    assert result.ok
    assert json.loads(result.text) == ["-p", "--no-session", "task" + suffix]


def test_missing_binary_returns_failure(tmp_path):
    result = OmpWorker({"cmd": str(tmp_path / "missing-omp")}).run("task", str(tmp_path))
    assert not result.ok and "worker binary not found" in result.text


def test_dispatch_at_omp(fake_omp, tmp_path):
    fake_omp("import sys\nprint(sys.argv[-1])")
    task = parse("@omp inspect files")
    bb = SimpleNamespace(cfg={"nim": {}}, omp=OmpWorker({}))
    result = Backbone._dispatch(bb, norm_worker(task.worker), task.prompt, str(tmp_path), True, 0)
    assert result.ok and result.text == "inspect files\nREAD-ONLY: do not edit or create files"


def test_discovery_and_doctor(fake_omp, tmp_path):
    fake_omp("import sys\nassert sys.argv[1:3] == ['-p', '--no-session']\nprint('ok')")
    caps = discover.discover(env={}, ssh_config=str(tmp_path / "missing"), project_roots=[str(tmp_path)])
    assert caps["agents"]["omp"] == str(tmp_path / "omp")
    report = doctor.run(caps["agents"], str(tmp_path), only=["omp"])
    assert len(report["agents"]) == 1 and report["agents"][0]["usable"]
    absent = discover.discover(env={}, which=lambda _: None,
                               ssh_config=str(tmp_path / "missing"), project_roots=[str(tmp_path)])
    assert doctor.run(absent["agents"], str(tmp_path), only=["omp"])["agents"] == []
