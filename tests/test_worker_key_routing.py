import json
import os
import subprocess
from types import SimpleNamespace
import pytest

from backbone.core import Backbone
from backbone.workers import ClineWorker, NimCallWorker, OmpWorker, OpencodeWorker, PiWorker


class FakePool:
    def __init__(self, alias="NIM_2", value="leased-value"):
        self.alias, self.secret = alias, value
        self.calls = []

    def call(self, fn, prefer=None, **kwargs):
        self.calls.append((prefer, kwargs))
        return fn(self.alias, self.secret)


class RetryPool:
    def __init__(self, names=("NIM_1", "NIM_2")):
        self.names = list(names)
        self.env = {name: f"loaded-only-test-secret-{name}-987654321" for name in self.names}
        self.attempted = []
        self.cooldowns = {}
        self.errors = []

    def call(self, fn, prefer=None, **kwargs):
        order = ([prefer] if prefer in self.names else []) + [n for n in self.names if n != prefer]
        last = None
        for name in order:
            self.attempted.append(name)
            try:
                return fn(name, self.env[name])
            except Exception as error:
                from backbone.keys import Transient
                if not isinstance(error, Transient):
                    raise
                self.errors.append(str(error))
                if error.retry_after:
                    self.cooldowns[name] = error.retry_after
                last = error
        from backbone.keys import Transient
        raise Transient(f"failed after {len(order)} attempts: {last}")


def test_pi_uses_temporary_child_auth_dir_and_cleans_on_timeout(monkeypatch, tmp_path):
    parent_dir = tmp_path / "owner-auth"
    parent_dir.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(parent_dir))
    observed = {}

    def timeout(cmd, cwd, env, timeout):
        observed.update(env=env.copy(), argv=cmd[:])
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr("backbone.workers._run", timeout)
    result = PiWorker({"thinking": "off", "timeout_s": 1}, "nvidia/model").run(
        "task", str(tmp_path), FakePool(), prefer="NIM_2")
    child_dir = observed["env"]["PI_CODING_AGENT_DIR"]
    assert child_dir != str(parent_dir) and not os.path.exists(child_dir)
    assert os.environ["PI_CODING_AGENT_DIR"] == str(parent_dir)
    assert "--thinking" in observed["argv"] and observed["argv"][observed["argv"].index("--thinking") + 1] == "off"
    assert "leased-value" not in observed["argv"]
    assert result.meta == {"failure_kind": "timeout", "retryable": False}


def test_pi_token_limit_truncation_is_terminal_and_keeps_key_slot(monkeypatch, tmp_path):
    from backbone import otel, workers
    from backbone.core import load_config

    monkeypatch.setattr(otel, "_TRACER", False)
    calls = []
    diagnostic = "Response was truncated: model reached output token limit, 143.85s"
    def run(cmd, cwd, env, timeout):
        calls.append((cmd[:], env["NVIDIA_API_KEY"]))
        return subprocess.CompletedProcess(cmd, 1, "", diagnostic)
    monkeypatch.setattr(workers, "_run", run)

    cfg = load_config()
    for key, name in [("db", "runs.db"), ("graph_db", "graph.db"),
                      ("tickets_dir", "tickets"), ("runs_dir", "runs"), ("work_dir", "work")]:
        cfg[key] = str(tmp_path / name)
    cfg["nim"]["keys"] = ["NIM_1", "NIM_2"]
    cfg["nim"]["auto_keys"] = False
    cfg["hooks"] = {}
    cfg["critic"] = {"when": "never"}
    router = Backbone(cfg, env={"NIM_1": "synthetic-key-one", "NIM_2": "synthetic-key-two"})
    result = router.run("bounded token-limit fixture", worker="nim1", gate="true",
                        cwd=str(tmp_path), isolate=False, prepared=True, use_vault=False)
    assert len(calls) == 1
    assert result["state"] == "blocked" and result["attempts"] == 1
    assert result["key_slot"] == "NIM_1"
    assert result["worker_meta"]["failure_kind"] == "truncated"
    assert result["worker_meta"]["retryable"] is False
    assert diagnostic in result.get("output", "")


def test_omp_explicit_key_isolated_without_profile_and_parent_unchanged(monkeypatch, tmp_path):
    parent_dir = tmp_path / "owner-auth"
    parent_dir.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(parent_dir))
    monkeypatch.setenv("NVIDIA_API_KEY", "parent-key")
    observed = {}

    def run(cmd, cwd, env, timeout):
        observed.update(argv=cmd[:], env=env.copy(), child=env["PI_CODING_AGENT_DIR"])
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    from backbone import workers
    old = workers._run
    workers._run = run
    try:
        result = OmpWorker({}).run("task", str(tmp_path), api_key="leased-value")
    finally:
        workers._run = old
    assert result.ok and not os.path.exists(observed["child"])
    assert "--profile" not in observed["argv"]
    assert observed["env"]["NVIDIA_API_KEY"] == "leased-value"
    assert "leased-value" not in observed["argv"]
    assert os.environ["PI_CODING_AGENT_DIR"] == str(parent_dir)
    assert os.environ["NVIDIA_API_KEY"] == "parent-key"


def test_omp_timeout_cleans_isolated_auth_dir(monkeypatch, tmp_path):
    observed = {}

    def timeout(cmd, cwd, env, timeout):
        observed["child"] = env["PI_CODING_AGENT_DIR"]
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr("backbone.workers._run", timeout)
    result = OmpWorker({"timeout_s": 1}).run("task", str(tmp_path), api_key="leased")
    assert not result.ok and result.meta == {"failure_kind": "timeout", "retryable": False}
    assert not os.path.exists(observed["child"])


def test_dispatch_omp_passes_leased_alias_and_value_and_records_slot():
    pool = FakePool("NIM_3", "leased-secret")
    seen = {}

    class Adapter:
        def run(self, prompt, cwd, **kwargs):
            seen.update(kwargs)
            from backbone.workers import Result
            return Result(True, "ok", "omp")

    bb = SimpleNamespace(cfg={"nim": {"default_key": "NIM_1"}, "workers": {}}, pool=pool, omp=Adapter())
    result = Backbone._dispatch_raw(bb, "omp:NIM_2", "p", ".", False, 0)
    assert seen["api_key"] == "leased-secret"
    assert pool.calls[0][0] == "NIM_2"
    assert result.key_slot == "NIM_3"


def test_dispatch_cline_passes_leased_alias_and_value():
    pool = FakePool("NIM_2", "leased-secret")
    seen = {}

    class Adapter:
        def run(self, prompt, cwd, **kwargs):
            seen.update(kwargs)
            from backbone.workers import Result
            return Result(True, "{\"result\":\"ok\"}", "cline")

    bb = SimpleNamespace(cfg={"nim": {"default_key": "NIM_1"}, "workers": {}}, pool=pool, cline=Adapter())
    result = Backbone._dispatch_raw(bb, "cline:NIM_3", "p", ".", False, 0)
    assert seen["api_key"] == "leased-secret" and seen["key"] == "NIM_2"
    assert pool.calls[0][0] == "NIM_3"
    assert result.key_slot == "NIM_2"


def test_cline_explicit_key_only_in_environment(monkeypatch, tmp_path):
    observed = {}

    def run(cmd, cwd, env, timeout):
        observed.update(argv=cmd[:], env=env.copy())
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "ok"}), "")

    monkeypatch.setattr("backbone.workers._run", run)
    result = ClineWorker({"flags": ["--provider", "nvidia", "--model", "nvidia/model"]}).run(
        "task", str(tmp_path), key="NIM_2", api_key="leased-secret")
    assert result.ok and result.key_slot == "NIM_2"
    assert observed["env"]["NVIDIA_API_KEY"] == "leased-secret"
    assert "leased-secret" not in observed["argv"]


def test_cline_explicit_key_fails_closed_without_nim_provider(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("cline must not run with the owner's default provider")
    monkeypatch.setattr("backbone.workers._run", forbidden)
    result = ClineWorker({}).run("task", str(tmp_path), key="NIM_2", api_key="leased-secret")
    assert not result.ok and result.meta["failure_kind"] == "missing_nim_provider"


def test_opencode_uses_selected_key_model_temp_config_and_cleans(monkeypatch, tmp_path):
    observed = {}

    def run(cmd, cwd, env, timeout):
        observed.update(argv=cmd[:], env=env.copy(), config_path=env["OPENCODE_CONFIG"])
        observed["config"] = json.loads(open(env["OPENCODE_CONFIG"], encoding="utf-8").read())
        return subprocess.CompletedProcess(cmd, 0, "answer", "")

    monkeypatch.setattr("backbone.workers._run", run)
    monkeypatch.setattr("backbone.workers._opencode_bin", lambda cmd: cmd)
    result = OpencodeWorker({"timeout_s": 4}, "nvidia/model-x", str(tmp_path)).run(
        "task", str(tmp_path), key="NIM_5", api_key="leased-secret")
    provider = observed["config"]["provider"]["nim"]
    assert result.ok and result.worker == "opencode:NIM_5"
    assert observed["env"]["NVIDIA_API_KEY"] == "leased-secret"
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {"baseURL": "https://integrate.api.nvidia.com/v1", "apiKey": "{env:NVIDIA_API_KEY}"}
    assert "nvidia/model-x" in provider["models"]
    assert "nim/nvidia/model-x" in observed["argv"]
    assert "leased-secret" not in str(observed["config"]) and "leased-secret" not in observed["argv"]
    assert not os.path.exists(os.path.dirname(observed["config_path"]))


def test_dispatch_opencode_leases_nim5_and_records_slot():
    pool = FakePool("NIM_5", "leased-secret")
    seen = {}

    class Adapter:
        def run(self, prompt, cwd, **kwargs):
            seen.update(kwargs)
            from backbone.workers import Result
            return Result(True, "ok", "opencode")

    bb = SimpleNamespace(cfg={"nim": {"default_key": "NIM_1"}, "workers": {}}, pool=pool, opencode=Adapter())
    result = Backbone._dispatch_raw(bb, "opencode:NIM_5", "p", ".", False, 0)
    assert seen["api_key"] == "leased-secret" and seen["key"] == "NIM_5"
    assert pool.calls[0][0] == "NIM_5" and result.key_slot == "NIM_5"


def test_opencode_timeout_is_terminal_and_cleans_config(monkeypatch, tmp_path):
    observed = {}

    def timeout(cmd, cwd, env, timeout):
        observed["path"] = env["OPENCODE_CONFIG"]
        raise subprocess.TimeoutExpired(cmd, timeout, output="partial", stderr="diagnostic")

    monkeypatch.setattr("backbone.workers._run", timeout)
    monkeypatch.setattr("backbone.workers._opencode_bin", lambda cmd: cmd)
    result = OpencodeWorker({"timeout_s": 1}, "nvidia/model", str(tmp_path)).run(
        "task", str(tmp_path), key="NIM_1", api_key="leased")
    assert not result.ok and result.meta["failure_kind"] == "timeout" and not result.meta["retryable"]
    assert "partial" in result.meta["partial_output"] and "diagnostic" in result.meta["partial_output"]
    assert not os.path.exists(os.path.dirname(observed["path"]))


def test_nim_chat_fails_closed_without_keypool():
    result = NimCallWorker({}, "model").run("task", ".", pool=None)
    assert not result.ok and result.meta["failure_kind"] == "missing_key_pool"


def test_nim_chat_rejects_truncated_completion(monkeypatch):
    from backbone import nim

    seen = {}
    def truncated(*args, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("NIM completion truncated: finish_reason=length")

    monkeypatch.setattr(nim, "chat", truncated)
    class Pool:
        def call(self, *args, **kwargs):
            return None
    result = NimCallWorker({"max_tokens": 3333}, "model", "http://example/v1").run("task", ".", pool=Pool())
    assert not result.ok and result.meta == {"failure_kind": "truncated", "retryable": False}
    assert seen["max_tokens"] == 3333 and seen["base_url"] == "http://example/v1"


def test_nim_http_finish_reason_length_is_rejected(monkeypatch):
    from backbone import nim

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}).encode()
    class Pool:
        def call(self, fn, **kwargs): return fn("NIM_1", "fake")
    monkeypatch.setattr(nim.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    try:
        nim.chat(Pool(), [], base_url="http://example/v1", model="m")
    except RuntimeError as exc:
        assert "finish_reason=length" in str(exc)
    else:
        assert False, "truncated response accepted"


@pytest.mark.parametrize("adapter_name", ["omp", "opencode", "cline"])
@pytest.mark.parametrize("status", [401, 403])
def test_leased_adapters_retry_auth_rejection_and_park_key(adapter_name, status):
    pool = RetryPool()
    class Adapter:
        def run(self, prompt, cwd, **kwargs):
            value = kwargs.get("api_key", "")
            if value == pool.env["NIM_1"]:
                from backbone.workers import Result
                return Result(False, f"HTTP {status} Unauthorized: {value}", adapter_name)
            from backbone.workers import Result
            return Result(True, "recovered", adapter_name)
    bb = SimpleNamespace(cfg={"nim": {"default_key": "NIM_1", "retries": 1}}, pool=pool,
                         omp=Adapter(), opencode=Adapter(), cline=Adapter())
    result = Backbone._dispatch_raw(bb, f"{adapter_name}:NIM_1", "p", ".", False, 0)
    assert result.ok and result.key_slot == "NIM_2"
    assert pool.attempted == ["NIM_1", "NIM_2"]
    assert pool.cooldowns["NIM_1"] == 3600.0
    assert all(pool.env["NIM_1"] not in error for error in pool.errors)


def test_exhausted_leased_error_is_redacted_before_persistence_and_return():
    pool = RetryPool()
    class Adapter:
        def run(self, prompt, cwd, **kwargs):
            from backbone.workers import Result
            return Result(False, f"HTTP 401 Unauthorized: {kwargs['api_key']}", "omp")
    class Runs:
        def __init__(self): self.ticket_values = []; self.run_values = []
        def ticket(self, rid, error, context):
            self.ticket_values.append((error, context)); return "ticket-id"
        def set(self, rid, state, error): self.run_values.append(error)
    class Graph:
        def __init__(self): self.bb = None
        def invoke(self, init, cfg):
            Backbone._dispatch_raw(self.bb, "omp:NIM_1", "p", ".", False, 0)
            return {"out": {}}
        def get_state(self, cfg): return SimpleNamespace(values={})
        def stop_beat(self, rid): pass
    graph, runs = Graph(), Runs()
    bb = SimpleNamespace(cfg={"nim": {"default_key": "NIM_1", "retries": 1}}, pool=pool,
                         omp=Adapter(), graph=graph, runs=runs)
    graph.bb = bb
    result = Backbone._invoke(bb, {}, "run-1")
    secret = pool.env["NIM_1"]
    assert result["state"] == "failed"
    assert secret not in result["error"]
    assert all(secret not in item for pair in runs.ticket_values for item in pair)
    assert all(secret not in item for item in runs.run_values)
