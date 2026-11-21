"""LeaseTable: overlap matrix, stale pid dropped, conflict reported."""
from __future__ import annotations

import os
from backbone.lease import LeaseTable, overlaps, normalize


def test_overlap_matrix():
    cwd = "/x"
    cases = [
        ("backbone/packet.py", "backbone/packet.py", True),   # exact
        ("backbone/*.py", "backbone/packet.py", True),        # glob vs path (fnmatch)
        ("backbone/packet.py", "backbone/*.py", True),
        ("backbone", "backbone/packet.py", True),             # directory prefix
        ("backbone/packet.py", "backbone", True),
        ("backbone/*.py", "lib/*.py", False),                 # disjoint directories
        ("src/*.py", "src/utils/*", True),                    # glob vs glob, prefix overlap
        ("src/a.py", "src/b.py", False),                      # same dir, different files
        ("docs/*.md", "docs/*", True),                        # glob vs glob, equal prefix
        ("data/dispatch-demo/pk-*.md", "data/other/*.md", False),
    ]
    for pa, pb, expect in cases:
        a, b = normalize(cwd, pa), normalize(cwd, pb)
        assert overlaps(a, b) == expect, (pa, pb)
        assert overlaps(b, a) == expect, (pb, pa)


def test_stale_pid_dropped():
    table = LeaseTable()
    table.acquire("stale-holder", "/x", ["f.py"], 123456789)  # pid that does not exist
    assert table.acquire("other", "/x", ["f.py"], os.getpid()) is None
    table.release("other")


def test_conflict_reported():
    table = LeaseTable()
    assert table.acquire("holder", "/x", ["shared.py"], os.getpid()) is None
    holder = table.acquire("waiter", "/x", ["shared.py"], os.getpid())
    assert holder is not None and holder["run_id"] == "holder"
    table.release("holder")
    # after release the waiter's path is free
    assert table.acquire("waiter", "/x", ["shared.py"], os.getpid()) is None
    table.release("waiter")
