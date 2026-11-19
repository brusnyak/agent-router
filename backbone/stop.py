"""Stop everything: guard pause, halt hub/daemon/node, optional VM sync.

Usage:
    python -m backbone stop            # pause + halt local processes (no VM sync)
    python -m backbone stop --sync     # also rsync to Oracle VM and restart router service
    python -m backbone stop --no-sync  # stop local only, no VM sync (same as default)

Safe: guard pause is fail-closed. Processes are terminated by PID file / pkill pattern.
In-flight runs finish or time out; no job is killed mid-write.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

from . import guard


def _run(cmd: list) -> int:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if p.stdout:
            print(p.stdout.strip())
        if p.stderr:
            print(p.stderr.strip(), file=sys.stderr)
        return p.returncode
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"stop: {cmd[0]} failed: {e}", file=sys.stderr)
        return 1


def _halt_processes() -> None:
    """Stop hub, daemon, and node processes. PID-file first, pattern fallback."""
    root = os.path.expanduser("~/.agent-router")
    for name, pidfile in (("hub", os.path.join(root, "router-daemon.pid")),
                          ("daemon", os.path.join(root, "router-daemon.pid")),
                          ("node", os.path.join(root, "router-node.pid"))):
        pid = ""
        try:
            with open(pidfile) as f:
                pid = f.read().strip()
        except OSError:
            pid = ""
        if pid:
            try:
                os.kill(int(pid), signal.SIGTERM)
                print(f"stop: terminated {name} (pid {pid})")
            except ProcessLookupError:
                print(f"stop: {name} (pid {pid}) not running")
            except PermissionError as e:
                print(f"stop: cannot terminate {name} (pid {pid}): {e}", file=sys.stderr)
    # Pattern fallback for any processes started without pid files
    for pattern in ("backbone serve", "backbone daemon", "backbone node"):
        _run(["pkill", "-TERM", "-f", pattern])


def main(sync: bool = True, no_sync: bool = False) -> int:
    if no_sync:
        sync = False
    # 1. Fail-closed: pause dispatch everywhere by writing the PAUSE file
    pf = guard.pause_files()
    root = os.path.dirname(os.path.abspath(pf[0]))
    os.makedirs(root, exist_ok=True)
    with open(pf[0], "w") as f:
        f.write(time.strftime("paused %Y-%m-%dT%H:%M:%S\n") + "stopped by backbone stop\n")
    hit = pf[0]
    print(f"stop: guard paused ({hit}) — no new dispatches")
    # 2. Halt local hub/daemon/node processes
    _halt_processes()
    # 3. Optional VM sync + restart
    if sync:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rc = _run(["sh", os.path.join(here, "scripts", "sync_vm.sh"), "--restart"])
        if rc != 0:
            print("stop: VM sync/restart failed; local stop still complete", file=sys.stderr)
            return 1
    print("stop: complete")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(prog="backbone stop")
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--no-sync", action="store_true")
    a = ap.parse_args()
    raise SystemExit(main(a.sync, a.no_sync))
