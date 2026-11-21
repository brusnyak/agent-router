"""Offline acceptance tests: never contact providers or load real credentials."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess

import pytest

from backbone import model_catalog as catalog

NOW = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize("row,expected", [
    ({"id": "x:free"}, True),
    ({"id": "x-free"}, True),
    ({"id": "free-money"}, False),
    ({"id": "x", "isFree": True}, True),
    ({"id": "x:free", "isFree": False}, False),
    ({"id": "x", "pricing": {"prompt": "0", "completion": 0}}, True),
    ({"id": "x:free", "pricing": {"prompt": "1", "completion": "0"}}, False),
    ({"id": "x", "pricing": {"prompt": "-1", "completion": "-1"}}, False),
    ({"id": "x", "pricing": {"prompt": "0"}}, False),
    ({"id": "x:free", "pricing": {"prompt": "NaN", "completion": "0"}}, False),
    ({"id": "x", "pricing": {"prompt": "0", "completion": "0", "request": "1"}}, False),
])
def test_free_requires_evidence(row, expected):
    assert catalog.is_free(row) is expected


def test_discover_api_sources(monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        return {"data": [{"id": "paid"}, {"id": "x:free"}, {"id": "x:free"}]}
    monkeypatch.setattr(catalog, "fetch", fetch)
    assert catalog.discover("nvidia") == ["paid", "x:free"]
    assert catalog.discover("kilo") == ["x:free"]
    assert catalog.discover("cline") == ["x:free"]
    assert calls == [catalog.BASES[p] + "/models" for p in ("nvidia", "kilo", "cline")]


def test_opencode_list(monkeypatch):
    def run(argv, **kwargs):
        assert argv == ["opencode", "models"]
        assert kwargs["timeout"] == catalog.TIMEOUT
        return subprocess.CompletedProcess(argv, 0, "opencode/x-free\nopencode/paid\nopencode/pickle\n"
                                           "openrouter/other:free\nwarning\nopencode/x-free\n")
    monkeypatch.setattr(catalog.subprocess, "run", run)
    monkeypatch.setattr(catalog, "fetch", lambda url: {"opencode": {"models": {
        "x-free": {"cost": {"input": 1, "output": 1}},
        "pickle": {"cost": {"input": 0, "output": 0}},
    }}})
    assert catalog.discover("opencode") == ["pickle"]


@pytest.mark.parametrize("data", [{}, {"data": {}}, {"data": [{"name": "bad"}]},
                                   {"data": [{"id": "unsafe\ntext"}]}])
def test_bad_discovery_is_not_empty_success(monkeypatch, data):
    monkeypatch.setattr(catalog, "fetch", lambda *a, **kw: data)
    with pytest.raises((ValueError, KeyError)):
        catalog.discover("cline")


def test_tiny_call_one_request(monkeypatch):
    monkeypatch.setenv("NIM_1", "synthetic-test-only")
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return {"choices": [{"message": {"content": "OK"}}]}
    monkeypatch.setattr(catalog, "fetch", fetch)
    result = catalog.tiny_call("nvidia", "test/model")
    assert result["ok"] and result["latency"] >= 0
    assert len(calls) == 1
    url, request = calls[0]
    assert url.endswith("/chat/completions")
    assert request["key"] == "synthetic-test-only"
    body = json.loads(request["data"])
    assert body["model"] == "test/model" and body["max_tokens"] == 8
    assert body["messages"] == [{"role": "user", "content": catalog.PROMPT}]


def test_missing_key_no_request(monkeypatch):
    monkeypatch.delenv("NIM_1", raising=False)
    monkeypatch.setattr(catalog, "fetch", lambda *a, **kw: pytest.fail("unexpected call"))
    assert catalog.tiny_call("nvidia", "x")["error"] == "missing_key"


@pytest.mark.parametrize("reply", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]}])
def test_http_success_requires_completion(monkeypatch, reply):
    monkeypatch.setenv("OPENCODE_API_KEY", "synthetic-test-only")
    monkeypatch.setattr(catalog, "fetch", lambda *a, **kw: reply)
    assert catalog.tiny_call("opencode", "x")["ok"] is False


def test_probe_uses_loader_and_masks_errors(monkeypatch):
    def run(argv, **kwargs):
        assert argv[:3] == [str(Path.home() / ".claude/scripts/with-env"), "CLINE_API_KEY", "--"]
        assert argv[-3:] == ["--probe", "cline", "test:free"]
        assert kwargs["capture_output"]
        raise RuntimeError("private response must never be stored")
    monkeypatch.setattr(catalog.subprocess, "run", run)
    result = catalog.probe("cline", "test:free")
    assert result == {"ok": False, "latency": None, "error": "RuntimeError"}


@pytest.fixture
def fake_providers(monkeypatch):
    monkeypatch.setattr(catalog, "discover", lambda p: ["test:free", "broken:free"])
    calls = []
    def probe(provider, model):
        calls.append((provider, model))
        return {"ok": model != "broken:free", "latency": 0.1}
    monkeypatch.setattr(catalog, "probe", probe)
    return calls


def test_daily_snapshots_and_cache(tmp_path, fake_providers):
    out = tmp_path / "model_catalog.json"
    result = catalog.snapshot(out, now=NOW)
    assert len(result["models"]) == 8 and len(fake_providers) == 8
    assert result["baseline"] is None and result["diff"]["new"] == []
    assert len(result["diff"]["failing"]) == 4
    for row in result["models"]:
        assert {"id", "free", "latency", "ok", "checked"} <= row.keys()
    assert json.loads(out.read_text()) == result
    assert json.loads((tmp_path / "model_catalog.diff.json").read_text()) == result["diff"]
    assert (tmp_path / "model_catalog/2026-11-20.json").exists()
    assert catalog.snapshot(out, now=NOW + timedelta(hours=1)) == result
    assert len(fake_providers) == 8
    catalog.snapshot(out, now=NOW, force=True)
    assert len(fake_providers) == 16


def test_actual_yesterday_diff_and_failed_source(tmp_path, fake_providers, monkeypatch):
    out = tmp_path / "model_catalog.json"
    catalog.snapshot(out, now=NOW - timedelta(days=1))
    def discover(provider):
        if provider == "cline":
            raise TimeoutError("secret error text")
        return ["new:free", "test:free"]
    monkeypatch.setattr(catalog, "discover", discover)
    report = catalog.snapshot(out, now=NOW)
    assert report["errors"] == {"cline": "TimeoutError"}
    assert report["diff"]["new"] == [f"{p}/new:free" for p in ("kilo", "nvidia", "opencode")]
    assert report["diff"]["removed"] == [f"{p}/broken:free" for p in ("kilo", "nvidia", "opencode")]
    assert report["diff"]["failing"] == []
    stale = [r for r in report["models"] if r["provider"] == "cline"]
    assert len(stale) == 2 and all(r["stale"] for r in stale)
    assert all(r["checked"].startswith("2026-11-19") for r in stale)
    assert "secret error text" not in out.read_text()
    # Re-running today must not compare against today's first receipt.
    assert catalog.snapshot(out, now=NOW, force=True)["diff"] == report["diff"]


def test_gap_is_not_yesterday(tmp_path, fake_providers):
    out = tmp_path / "model_catalog.json"
    catalog.snapshot(out, now=NOW - timedelta(days=2))
    assert catalog.snapshot(out, now=NOW)["baseline"] is None


def test_concurrent_snapshots_probe_once(tmp_path, fake_providers):
    from concurrent.futures import ThreadPoolExecutor
    out = tmp_path / "model_catalog.json"
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(catalog.snapshot, out, now=NOW) for _ in range(2)]
        reports = [future.result(timeout=5) for future in futures]
    assert reports[0] == reports[1]
    assert len(fake_providers) == 8


def test_failed_replace_preserves_existing_file(tmp_path, monkeypatch):
    out = tmp_path / "receipt.json"
    out.write_text('{"previous": true}')
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(catalog.os, "replace", fail)
    with pytest.raises(OSError):
        catalog.atomic_json(out, {"replacement": True})
    assert json.loads(out.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [out]


def test_cli_wiring(monkeypatch, capsys, tmp_path):
    from backbone.cli import main
    calls = []
    monkeypatch.setattr(catalog, "snapshot", lambda path, **kw: calls.append((path, kw)) or {"models": []})
    main(["catalog", "models", "--out", str(tmp_path / "out.json"), "--force"])
    assert calls == [(str(tmp_path / "out.json"), {"force": True})]
    assert json.loads(capsys.readouterr().out) == {"models": []}
