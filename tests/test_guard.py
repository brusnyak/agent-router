"""Unattended-safety guard, dispatch wiring, doctor->routing freshness, swarm result, dead-key failover. Temp dirs only."""
import io
import json
import time
import urllib.error
from types import SimpleNamespace

import pytest

from backbone import guard, health
from backbone.core import Backbone
from backbone.workers import Result


@pytest.fixture(autouse=True)
def no_real_pause(monkeypatch, tmp_path):
    from backbone import keys, otel
    monkeypatch.setattr(keys, "STATE_FILE", str(tmp_path / "key_state.json"))
    monkeypatch.setattr(otel, "_TRACER", False)
    monkeypatch.setenv("BACKBONE_PAUSE_FILES", "")          # a real PAUSE file on this machine must not affect tests
    for k in ("BACKBONE_UNATTENDED", "BACKBONE_UNATTENDED_ALLOW", "BACKBONE_BUDGET_CALLS", "BACKBONE_BUDGET_USD"):
        monkeypatch.delenv(k, raising=False)


def test_pause_file_blocks_everything(tmp_path, monkeypatch):
    f = tmp_path / "PAUSE"
    monkeypatch.setenv("BACKBONE_PAUSE_FILES", str(f))
    assert guard.check("nim1", False) is False
    f.write_text("x")
    with pytest.raises(guard.Blocked, match="paused"):
        guard.check("nim1", False)
    assert guard.status()["paused"] == str(f)


def test_call_and_usd_budgets(tmp_path):
    led = guard.Ledger(str(tmp_path / "l.db"))
    for _ in range(3):
        led.record("nim1", True, 0.4)
    with pytest.raises(guard.Blocked, match="budget"):
        guard.check("nim1", False, env={"BACKBONE_BUDGET_CALLS": "3", "BACKBONE_PAUSE_FILES": ""}, ledger=led)
    assert guard.check("nim1", False, env={"BACKBONE_BUDGET_CALLS": "4", "BACKBONE_PAUSE_FILES": ""}, ledger=led) is False
    with pytest.raises(guard.Blocked, match=r"\$"):
        guard.check("nim1", False, cfg={"guard": {"usd_per_day": 1.0}}, env={"BACKBONE_PAUSE_FILES": ""}, ledger=led)
    assert led.today()["nim1"] == {"calls": 3, "usd": 1.2}


def test_unattended_forces_read_only_and_denies_experts(tmp_path):
    env = {"BACKBONE_UNATTENDED": "1", "BACKBONE_PAUSE_FILES": ""}
    led = guard.Ledger(str(tmp_path / "l.db"))
    assert guard.check("nim1", False, env=env, ledger=led) is True
    with pytest.raises(guard.Blocked, match="expert"):
        guard.check("claude", False, env=env)
    assert guard.check("claude", False, env={**env, "BACKBONE_UNATTENDED_ALLOW": "claude"}, ledger=led) is True
    for _ in range(guard.UNATTENDED_DEFAULT_CALLS):
        led.record("nim1", True)
    with pytest.raises(guard.Blocked, match="budget"):                         # fail closed: default cap when nothing configured
        guard.check("nim1", False, env=env, ledger=led)


def test_dispatch_is_guarded_recorded_and_masked(tmp_path, monkeypatch):
    bb = SimpleNamespace(cfg={"db": str(tmp_path / "x.db"), "guard": {"calls_per_day": 1}, "nim": {}})
    monkeypatch.setattr(Backbone, "_dispatch_raw", lambda self, spec, p, c, ro, a: Result(True, "ok", spec, meta={"cost_usd": 0.5, "ro": ro}))
    r1 = Backbone._dispatch(bb, "nim1", "p", ".", False, 0)
    assert r1.ok and r1.meta["ro"] is False
    r2 = Backbone._dispatch(bb, "nim1", "p", ".", False, 0)
    assert not r2.ok and r2.text.startswith("blocked: budget")
    assert guard.Ledger(str(tmp_path / "ledger.db")).today() == {"nim1": {"calls": 1, "usd": 0.5}}


def test_unknown_worker_lists_known_names(tmp_path):
    bb = SimpleNamespace(cfg={"nim": {}})
    r = Backbone._dispatch(bb, "nope", "p", ".", True, 0)       # stand-in has no workers: must not raise AttributeError
    assert not r.ok and "unknown worker 'nope'" in r.text and "known:" in r.text and "omp" in r.text


def test_real_backbone_has_every_advertised_worker_attribute():
    bb = Backbone.__new__(Backbone)
    Backbone.__init__.__code__                                   # constructor wires these; names must exist in source
    src = open(Backbone.__init__.__code__.co_filename).read()
    for attr in ("self.omp =", "self.cline =", "self.agy ="):
        assert attr in src


def test_doctor_results_reach_routing_only_when_fresh(tmp_path):
    p = tmp_path / "doctor.json"
    health.save(str(p), {"agents": [{"name": "opencode", "usable": False}, {"name": "claude", "usable": True}]})
    assert health.unusable(str(p)) == {"opencode"}
    d = json.load(open(p))
    d["saved_at"] = time.time() - 7 * 3600
    p.write_text(json.dumps(d))
    assert health.unusable(str(p)) == set()                      # stale = unknown = allowed
    assert health.unusable(str(tmp_path / "missing.json")) == set()


def test_swarm_returns_a_result_with_two_or_more_subtasks():
    bb = SimpleNamespace(cfg={}, pool=SimpleNamespace(rpm_limit=40, names=["NIM_1", "NIM_2"]))
    bb.chat = lambda *a, **k: '["do a", "do b"]'
    bb.fanout = lambda subs, **k: [{"output": f"out {s}"} for s in subs]
    bb.run = lambda *a, **k: {"output": "merged"}
    out = Backbone.swarm(bb, "goal")
    assert out["final"] == {"output": "merged"} and out["plan"] == ["do a", "do b"] and len(out["results"]) == 2


def test_rejected_key_fails_over_and_is_parked(monkeypatch):
    from backbone import nim
    from backbone.keys import KeyPool

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()

    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append(req.headers.get("Authorization", ""))
        if "k1" in seen[-1]:
            raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, io.BytesIO(b"bad key"))
        return Resp()

    monkeypatch.setattr(nim.urllib.request, "urlopen", fake_urlopen)
    pool = KeyPool(["NIM_1", "NIM_2"], env={"NIM_1": "k1", "NIM_2": "k2"})
    ask = lambda: nim.chat(pool, [{"role": "user", "content": "x"}], base_url="http://x/v1", model="m", prefer="NIM_1", retries=1, backoff_s=0)
    assert ask() == "hi" and ask() == "hi"
    assert sum("k1" in a for a in seen) == 1          # rejected once, then parked: the second call never touches NIM_1
    assert sum("k2" in a for a in seen) == 2
