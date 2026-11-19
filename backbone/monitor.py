"""Portable resource snapshots; executable over SSH with only the stdlib."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess


DEFAULT_LIMITS = {
    "load_per_cpu": 0.9,
    "mem_avail_mb": 800,
    "disk_root_pct": 90,
    "swap_used_mb": 1500,
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(args) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=True,
                          timeout=10).stdout


def parse_meminfo(text: str) -> dict:
    """Linux /proc/meminfo values are KiB; return MiB."""
    values = {}
    for line in text.splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.split()[0])
    avail = values.get("MemAvailable")
    if avail is None:
        avail = (values.get("MemFree", 0) + values.get("Buffers", 0)
                 + values.get("Cached", 0) + values.get("SReclaimable", 0)
                 - values.get("Shmem", 0))
    return {"mem_total_mb": values["MemTotal"] / 1024,
            "mem_avail_mb": max(0, avail) / 1024,
            "swap_used_mb": (values["SwapTotal"] - values["SwapFree"]) / 1024}


def parse_vm_stat(text: str) -> float:
    """Free, inactive and speculative Darwin pages, in MiB."""
    page_size = int(re.search(r"page size of (\d+) bytes", text).group(1))
    pages = {}
    for line in text.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            pages[key] = int(value.strip().rstrip("."))
    return sum(pages.get(k, 0) for k in
               ("Pages free", "Pages inactive", "Pages speculative")) * page_size / 1024**2


def parse_swapusage(text: str) -> float:
    match = re.search(r"used\s*=\s*([\d.]+)([KMGT])", text)
    if not match:
        raise ValueError("invalid vm.swapusage")
    return float(match.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2}[match.group(2)]


def parse_ps(text: str) -> list:
    procs = []
    for line in text.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2:
            procs.append({"name": fields[1], "rss_mb": int(fields[0]) / 1024})
    return sorted(procs, key=lambda p: p["rss_mb"], reverse=True)[:5]


def collect() -> dict:
    snap = {"host": socket.gethostname(), "ts": _ts(), "cpus": os.cpu_count() or 1}
    system = platform.system()
    if system == "Darwin":
        loads = os.getloadavg()
        snap.update(mem_total_mb=int(_run(["sysctl", "-n", "hw.memsize"])) / 1024**2,
                    mem_avail_mb=parse_vm_stat(_run(["vm_stat"])),
                    swap_used_mb=parse_swapusage(_run(["sysctl", "-n", "vm.swapusage"])))
    elif system == "Linux":
        loads = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
        snap.update(parse_meminfo(Path("/proc/meminfo").read_text()))
    else:
        raise RuntimeError(f"unsupported platform: {system}")
    snap.update(zip(("load1", "load5", "load15"), loads))
    disk = os.statvfs("/")
    used = disk.f_blocks - disk.f_bfree
    snap["disk_root_pct"] = 100 * used / (used + disk.f_bavail) if used + disk.f_bavail else 0.0
    snap["top_procs"] = parse_ps(_run(["ps", "-axo", "rss=,comm="]))
    return snap


def remote(host: str) -> dict:
    try:
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:@-]*", host):
            raise ValueError("invalid SSH host")
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, "python3", "-"],
            input=Path(__file__).read_text(), capture_output=True, text=True,
            check=True, timeout=20)
        snap = json.loads(result.stdout)
        required = {"host", "ts", "cpus", "load1", "load5", "load15", "mem_total_mb",
                    "mem_avail_mb", "swap_used_mb", "disk_root_pct", "top_procs"}
        if not isinstance(snap, dict) or not required.issubset(snap):
            raise ValueError("incomplete remote snapshot")
        snap["host"] = host
        return snap
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        return {"host": host, "error": str(detail).strip(), "ts": _ts()}


def check(snap: dict, limits: dict | None = None) -> list[str]:
    if "error" in snap:
        return [f"collection failed: {snap['error']}"]
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    alerts = []
    ratio = snap["load1"] / max(1, snap["cpus"])
    if ratio > limits["load_per_cpu"]:
        alerts.append(f"load1/cpus {ratio:.2f} > {limits['load_per_cpu']}")
    for key, low in (("mem_avail_mb", True), ("disk_root_pct", False), ("swap_used_mb", False)):
        value, limit = snap[key], limits[key]
        if (value < limit) if low else (value > limit):
            alerts.append(f"{key} {value:.1f} {'<' if low else '>'} {limit}")
    return alerts


def ok_to_dispatch(snap: dict) -> tuple[bool, str]:
    if "error" in snap:
        return False, f"collection failed: {snap['error']}"
    if snap["load1"] >= 10:
        return True, f"warning: load1 {snap['load1']:.1f} >= 10; dispatch still allowed but host is heavily loaded"
    if snap["mem_avail_mb"] < 500:
        return False, "mem_avail_mb < 500"
    return True, "resources available"
if __name__ == "__main__":
    print(json.dumps(collect()))
