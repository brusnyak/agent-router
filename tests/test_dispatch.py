"""Dispatch: fake run, disjoint packets overlap in time, overlapping serialise, dry-run waves."""
from __future__ import annotations

import threading
import time

from backbone.core import Backbone


def _write_packet(path, name, writes):
    with open(path, "w") as fh:
        fh.write(f"# Packet {name}\nGoal: {name}\nAllowed writes: {writes}\n")


def test_dry_run_waves(tmp_path):
    bb = Backbone()
    pa = tmp_path / "pk-a.md"; pb = tmp_path / "pk-b.md"; pc = tmp_path / "pk-c.md"
    _write_packet(pa, "a", "x/one.py")
    _write_packet(pb, "b", "y/two.py")
    _write_packet(pc, "c", "x/*.py")  # overlaps a
    plan = bb.dispatch([str(pa), str(pb), str(pc)], cwd=str(tmp_path), dry_run=True)
    waves = [w["packets"] for w in plan]
    assert waves == [["pk-a", "pk-b"], ["pk-c"]], waves


def test_disjoint_overlap_in_time(tmp_path):
    bb = Backbone()
    pa = tmp_path / "p1.md"; pb = tmp_path / "p2.md"
    _write_packet(pa, "p1", "x/one.py")
    _write_packet(pb, "p2", "y/two.py")
    events = []
    lock = threading.Lock()

    def fake_run(text, *, session=None, project="", cwd=None, gate=None, isolate=True,
                 worker="", read_only=False, use_vault=True, escalate=None,
                 on_start=None, prepared=False):
        start = time.monotonic()
        with lock:
            events.append(("start", start))
        time.sleep(0.2)
        with lock:
            events.append(("end", time.monotonic()))
        return {"state": "done", "gate_passed": True, "worker": worker}

    bb.run = fake_run
    results = bb.dispatch([str(pa), str(pb)], cwd=str(tmp_path), max_parallel=4)
    assert len(results) == 2 and all(r["state"] == "done" for r in results)
    starts = [t for k, t in events if k == "start"]
    ends = [t for k, t in events if k == "end"]
    assert starts[1] < ends[0], "disjoint packets should run concurrently"


def test_overlapping_serialize(tmp_path):
    bb = Backbone()
    pa = tmp_path / "p1.md"; pb = tmp_path / "p2.md"
    _write_packet(pa, "p1", "x/one.py")
    _write_packet(pb, "p2", "x/*.py")  # overlaps p1
    events = []
    lock = threading.Lock()

    def fake_run(text, *, session=None, project="", cwd=None, gate=None, isolate=True,
                 worker="", read_only=False, use_vault=True, escalate=None,
                 on_start=None, prepared=False):
        start = time.monotonic()
        with lock:
            events.append(("start", start))
        time.sleep(0.2)
        with lock:
            events.append(("end", time.monotonic()))
        return {"state": "done", "gate_passed": True, "worker": worker}

    bb.run = fake_run
    results = bb.dispatch([str(pa), str(pb)], cwd=str(tmp_path), max_parallel=4)
    assert all(r["state"] == "done" for r in results)
    starts = [t for k, t in events if k == "start"]
    ends = [t for k, t in events if k == "end"]
    assert starts[1] >= ends[0] - 1e-9, "overlapping packets should serialise"
