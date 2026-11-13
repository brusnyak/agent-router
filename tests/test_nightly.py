import os
import subprocess
from pathlib import Path

S = Path(__file__).resolve().parent.parent / "scripts" / "nightly.sh"


def test_dry_prints_four_commands_in_order():
    r = subprocess.run(["sh", str(S)], env={**os.environ, "NIGHTLY_DRY": "1"},
                       capture_output=True, text=True, cwd="/")
    assert r.returncode == 0
    keys = ["build_catalog.py", "shadow_enrich.py --limit 500", "librarian.py", "hook_log report --json"]
    lines = r.stdout.splitlines()
    assert len(lines) == 5 and lines[4].startswith("nightly done")
    assert all(k in l for k, l in zip(keys, lines))


def test_syntax():
    assert subprocess.run(["sh", "-n", str(S)]).returncode == 0


def test_no_rm_no_sudo():
    t = S.read_text()
    assert "rm " not in t and "sudo" not in t
