#!/usr/bin/env python3
"""
Auto-refresh orchestration graph watcher for agent-router.

Watches agent-router log files and re-renders the Mermaid graph whenever
they change. Output is written to a .mmd file and optionally to stdout.

Usage:
    python3 scripts/watch_graph.py [--interval 5] [--output graph.mmd] [--window 60]

The output file is updated in place — point a Mermaid viewer at it for
live, non-static visualization of which models are invoked when.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(os.path.expanduser("~/.agent-router"))
LOG_FILES = [BASE / "hook-shadow.jsonl", BASE / "outcomes.jsonl", BASE / "enforce.jsonl"]
GRAPH_SCRIPT = Path(os.path.expanduser("~/Developer/agent-router/scripts/graph_orchestration.py"))


def _file_hash(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_hashes() -> str:
    return hashlib.sha256("".join(_file_hash(p) for p in LOG_FILES).encode()).hexdigest()


def render(window: int) -> str:
    result = subprocess.run(
        [sys.executable, str(GRAPH_SCRIPT), str(window)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"%% Error rendering graph: {result.stderr}"
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-refresh agent-router graph")
    parser.add_argument("--interval", type=int, default=5, help="Poll interval in seconds")
    parser.add_argument("--output", type=str, default=None, help="Output .mmd file path")
    parser.add_argument("--window", type=int, default=60, help="Time window in minutes")
    args = parser.parse_args()

    output = Path(args.output).expanduser() if args.output else None
    last_hash = ""

    print(f"Watching agent-router logs (interval={args.interval}s, window={args.window}m)...")
    if output:
        print(f"Output: {output}")
    print("Ctrl+C to stop\n")

    try:
        while True:
            current_hash = _all_hashes()
            if current_hash != last_hash and current_hash:
                graph = render(args.window)
                if output:
                    output.write_text(graph)
                    print(f"[{time.strftime('%H:%M:%S')}] Graph updated -> {output}")
                else:
                    print(graph)
                    print("---" * 20)
                last_hash = current_hash
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
