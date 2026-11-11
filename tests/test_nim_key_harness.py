"""Tests for the NIM key harness: rotation, backoff, cooldown, quarantine."""
import os
import sys
from unittest.mock import patch

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import nim_key_harness as h  # noqa: E402
from nim_key_harness import NimKeyHarness  # noqa: E402


def _mk(keys=("NIM_1", "NIM_2", "NIM_3")):
    """Harness with fake key values so no real secret is needed."""
    for k in keys:
        os.environ[k] = "fake-" + k
    return NimKeyHarness(key_envs=keys)


def test_get_client_round_robin():
    hn = _mk()
    seen = [hn.get_client() for _ in range(4)]
    assert seen == ["NIM_1", "NIM_2", "NIM_3", "NIM_1"], seen


def test_get_client_honours_preferred():
    hn = _mk()
    assert hn.get_client(preferred="NIM_3") == "NIM_3"


def test_get_client_skips_parked_key():
    hn = _mk()
    hn.mark_key_unhealthy("NIM_1", 60)
    assert hn.get_client() == "NIM_2"


def test_get_client_skips_missing_key():
    # a key name present in no env file at all -> unusable
    hn = _mk(keys=("NIM_1", "NIM_2"))
    hn.key_envs = ["NIM_NOT_A_REAL_KEY", "NIM_2"]  # first one is in no env file
    assert hn.get_client() == "NIM_2"


def test_get_client_returns_none_when_all_unhealthy():
    hn = _mk()
    for k in ("NIM_1", "NIM_2", "NIM_3"):
        hn.mark_key_unhealthy(k, 60)
    assert hn.get_client() is None


def test_retry_rotates_to_next_key_on_429():
    hn = _mk()
    calls = []

    def fake_chat(model, messages, **kw):
        calls.append(kw.get("key_order"))
        if len(calls) == 1:
            raise RuntimeError("http 429")
        return {"content": "ok"}

    with patch.object(h.nim_call, "chat", fake_chat), patch.object(h.time, "sleep"):
        out = hn.call_with_retry([{"role": "user", "content": "x"}], attempts=3)
    assert out["content"] == "ok"
    assert calls == [["NIM_1"], ["NIM_2"]], calls


def test_retry_quarantines_dead_key_and_rotates():
    hn = _mk()
    calls = []

    def fake_chat(model, messages, **kw):
        calls.append(kw.get("key_order"))
        if len(calls) == 1:
            raise RuntimeError("http 403")
        return {"content": "ok"}

    with patch.object(h.nim_call, "chat", fake_chat), patch.object(h.time, "sleep"):
        out = hn.call_with_retry([{"role": "user", "content": "x"}], attempts=3)
    assert out["content"] == "ok"
    assert calls[0] == ["NIM_1"] and calls[1] == ["NIM_2"], calls  # rotated off the dead key
    assert "NIM_1" in hn._dead
    assert hn.get_client() != "NIM_1"  # dead key stays quarantined


def test_retry_does_not_retry_fatal_4xx():
    hn = _mk()
    calls = []

    def fake_chat(model, messages, **kw):
        calls.append(1)
        raise RuntimeError("http 400")

    with patch.object(h.nim_call, "chat", fake_chat), patch.object(h.time, "sleep"):
        try:
            hn.call_with_retry([{"role": "user", "content": "x"}], attempts=3)
            assert False, "should have raised"
        except RuntimeError as e:
            assert "http 400" in str(e)
    assert len(calls) == 1, calls


def test_retry_sleeps_with_exponential_backoff():
    hn = _mk()
    slept = []

    def fake_chat(model, messages, **kw):
        raise RuntimeError("TimeoutError")

    with patch.object(h.nim_call, "chat", fake_chat), \
         patch.object(h.time, "sleep", lambda s: slept.append(s)):
        try:
            hn.call_with_retry([{"role": "user", "content": "x"}], attempts=3)
        except RuntimeError:
            pass
    assert slept == [1.0, 2.0], slept


def test_retry_gives_up_after_attempts():
    hn = _mk()
    n = []

    def fake_chat(model, messages, **kw):
        n.append(1)
        raise RuntimeError("http 500")

    with patch.object(h.nim_call, "chat", fake_chat), patch.object(h.time, "sleep"):
        try:
            hn.call_with_retry([{"role": "user", "content": "x"}], attempts=3)
            assert False, "should have raised"
        except RuntimeError as e:
            assert "3 attempt" in str(e)
    assert len(n) == 3, n


def test_chain_model_rejected():
    hn = _mk()
    try:
        hn.call_with_retry([{"role": "user", "content": "x"}], model="chain")
        assert False, "should have raised"
    except ValueError:
        pass
