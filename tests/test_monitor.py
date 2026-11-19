"""Offline resource-monitor fixtures; never contact an SSH host."""
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from backbone import monitor


MEMINFO = """MemTotal: 8388608 kB
MemAvailable: 2097152 kB
SwapTotal: 2097152 kB
SwapFree: 1572864 kB
"""
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free: 100.
Pages active: 900.
Pages inactive: 200.
Pages speculative: 20.
Pages wired down: 40.
Pages occupied by compressor: 70.
"""


def snapshot(**overrides):
    return {"host": "fixture", "ts": "2026-11-17T00:00:00+00:00", "cpus": 4,
            "load1": 1.0, "load5": 0.8, "load15": 0.5,
            "mem_total_mb": 8192, "mem_avail_mb": 2048, "swap_used_mb": 0,
            "disk_root_pct": 40, "top_procs": [], **overrides}


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("unmocked subprocess")
    monkeypatch.setattr(monitor.subprocess, "run", blocked)


def test_meminfo():
    assert monitor.parse_meminfo(MEMINFO) == {
        "mem_total_mb": 8192, "mem_avail_mb": 2048, "swap_used_mb": 512}


def test_meminfo_fallback():
    text = MEMINFO.replace("MemAvailable: 2097152 kB", "MemFree: 1024 kB\nBuffers: 2048 kB\nCached: 4096 kB")
    assert monitor.parse_meminfo(text)["mem_avail_mb"] == 7


@pytest.mark.parametrize("page_size", [4096, 16384])
def test_vm_stat(page_size):
    assert monitor.parse_vm_stat(VM_STAT.replace("16384", str(page_size))) == 320 * page_size / 1024**2


@pytest.mark.parametrize("text, expected", [("total = 2.00G used = 1.50G free = 0.50G", 1536),
                                            ("used = 512.00M", 512), ("used = 1024K", 1)])
def test_swapusage(text, expected):
    assert monitor.parse_swapusage(text) == expected


def test_top_procs():
    rows = "\n".join(f"{i * 1024} /bin/process {i}" for i in range(1, 8))
    procs = monitor.parse_ps(rows)
    assert len(procs) == 5
    assert procs[0] == {"name": "/bin/process 7", "rss_mb": 7}
    assert procs[-1]["rss_mb"] == 3


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_collect(system, monkeypatch):
    monkeypatch.setattr(monitor.platform, "system", lambda: system)
    monkeypatch.setattr(monitor.os, "cpu_count", lambda: 4)
    monkeypatch.setattr(monitor.os, "getloadavg", lambda: (1.0, 0.8, 0.5))
    monkeypatch.setattr(monitor.os, "statvfs", lambda path: SimpleNamespace(f_blocks=100, f_bfree=40, f_bavail=30))
    monkeypatch.setattr(monitor.Path, "read_text", lambda p: MEMINFO if str(p) == "/proc/meminfo" else "1.0 0.8 0.5 1/2 3")
    outputs = {("sysctl", "-n", "hw.memsize"): str(8192 * 1024**2),
               ("sysctl", "-n", "vm.swapusage"): "used = 512.00M",
               ("vm_stat",): VM_STAT, ("ps", "-axo", "rss=,comm="): "1024 python"}
    monkeypatch.setattr(monitor, "_run", lambda args: outputs[tuple(args)])
    snap = monitor.collect()
    assert set(snap) == set(snapshot())
    assert snap["load1"] == 1 and snap["cpus"] == 4
    assert snap["mem_total_mb"] == 8192 and snap["swap_used_mb"] == 512
    assert snap["mem_avail_mb"] == (2048 if system == "Linux" else 5)
    assert snap["disk_root_pct"] == pytest.approx(100 * 60 / 90)
    assert snap["top_procs"] == [{"name": "python", "rss_mb": 1}]
    assert datetime.fromisoformat(snap["ts"]).tzinfo is not None


def test_threshold_boundaries():
    assert monitor.check(snapshot(load1=3.6, mem_avail_mb=800, disk_root_pct=90, swap_used_mb=1500)) == []
    assert len(monitor.check(snapshot(load1=3.61, mem_avail_mb=799, disk_root_pct=90.1, swap_used_mb=1501))) == 4
    assert monitor.check(snapshot(load1=4), {"load_per_cpu": 1.1}) == []
    assert len(monitor.check(snapshot(), {"mem_avail_mb": 3000, "disk_root_pct": 30, "swap_used_mb": -1})) == 3


@pytest.mark.parametrize("values, expected", [({}, True), ({"load1": 5.99}, True),
    ({"load1": 6}, True), ({"load1": 9.9}, True), ({"load1": 10}, True),
    ({"mem_avail_mb": 499}, False), ({"mem_avail_mb": 500}, True)])
def test_dispatch(values, expected):
    ok, reason = monitor.ok_to_dispatch(snapshot(**values))
    assert ok is expected and reason
    if values.get("load1", 0) >= 10:
        assert "warning" in reason and "load1" in reason


def test_error_snapshot():
    snap = {"host": "unavailable", "ts": "now", "error": "timeout"}
    assert monitor.check(snap) == ["collection failed: timeout"]
    assert monitor.ok_to_dispatch(snap) == (False, "collection failed: timeout")


@pytest.mark.parametrize("error", [OSError("no ssh"), monitor.subprocess.CalledProcessError(255, "ssh", stderr="denied"),
                                   monitor.subprocess.TimeoutExpired("ssh", 20)])
def test_remote_error(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(monitor.subprocess, "run", fail)
    snap = monitor.remote("oracle-vm")
    assert set(snap) == {"host", "error", "ts"}
    assert snap["host"] == "oracle-vm" and snap["error"]
    datetime.fromisoformat(snap["ts"])


@pytest.mark.parametrize("output", ["garbage", "[]", "{}"])
def test_remote_invalid_output(monkeypatch, output):
    monkeypatch.setattr(monitor.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=output))
    assert "error" in monitor.remote("oracle-vm")


def test_remote_source(monkeypatch):
    def run(args, **kwargs):
        assert args == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "oracle-vm", "python3", "-"]
        assert "def collect()" in kwargs["input"]
        assert kwargs["check"] and kwargs["timeout"] == 20
        return SimpleNamespace(stdout=json.dumps(snapshot()))
    monkeypatch.setattr(monitor.subprocess, "run", run)
    assert monitor.remote("oracle-vm") == snapshot(host="oracle-vm")


@pytest.mark.parametrize("host", ["-oProxyCommand=bad", "a;id", "../escape"])
def test_remote_rejects_unsafe_host(host):
    assert "error" in monitor.remote(host)


@pytest.mark.parametrize("alert", [False, True])
def test_cli_local_json_write(tmp_path, monkeypatch, capsys, alert):
    from backbone import cli, core
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(core, "load_config", lambda: {"monitor": {"mem_avail_mb": 3000 if alert else 800}})
    monkeypatch.setattr(monitor, "collect", lambda: snapshot())
    monkeypatch.setattr(cli, "Backbone", lambda: pytest.fail("monitor must not initialize Backbone"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["monitor", "--json", "--write"])
    assert exc.value.code == (2 if alert else 0)
    assert json.loads(capsys.readouterr().out) == snapshot()
    assert json.loads((tmp_path / ".agent-router/monitor/fixture.json").read_text()) == snapshot()


def test_cli_multiple_hosts(monkeypatch, capsys):
    from backbone import cli, core
    monkeypatch.setattr(core, "load_config", lambda: {})
    monkeypatch.setattr(monitor, "remote", lambda host: snapshot(host=host))
    with pytest.raises(SystemExit) as exc:
        cli.main(["monitor", "--host", "one", "two", "--host", "three", "--json"])
    assert exc.value.code == 0
    assert [s["host"] for s in json.loads(capsys.readouterr().out)] == ["one", "two", "three"]


def test_cli_collection_failure(monkeypatch, capsys):
    from backbone import cli, core
    monkeypatch.setattr(core, "load_config", lambda: {})
    def fail():
        raise monitor.subprocess.TimeoutExpired("ps", 10)
    monkeypatch.setattr(monitor, "collect", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main(["monitor"])
    assert exc.value.code == 2
    assert "collection failed" in capsys.readouterr().out
