#!/usr/bin/env python3
"""Browser pre-flight check for agent-router.

Detects Neo (BrowserClaw) and Ego lite, checks if running, starts if down,
and flags whether chat-based browser interaction (e.g. Gemini deep research)
is available.

Never installs anything — only detects and launches.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List

KNOWN_BROWSERS = [
    {"id": "browserclaw", "name": "BrowserClaw", "bundle": "com.browseros.BrowserClaw"},
    {"id": "ego-lite", "name": "ego lite", "bundle": "com.citrolabs.ego.lite"},
]


def _mdls(bundle_id: str) -> str | None:
    try:
        out = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def _running(name: str) -> bool:
    try:
        out = subprocess.run(["pgrep", "-ax", name],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return bool(out)
    except Exception:
        return False


def _launch(name: str) -> dict:
    """Attempt to launch the browser. Returns {ok, error}."""
    try:
        subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=10)
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_browsers(auto_start: bool = False) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for b in KNOWN_BROWSERS:
        app_path = _mdls(b["bundle"])
        running = _running(b["name"])
        entry = {
            "id": b["id"],
            "display_name": b["name"],
            "bundle_id": b["bundle"],
            "app_path": app_path,
            "installed": app_path is not None,
            "running": running,
            "launch_cmd": f'open -a "{b["name"]}"',
            "chat_based_interaction": False,  # set True after successful launch + chat UI detected
        }
        if not running and auto_start and app_path:
            launch_result = _launch(b["name"])
            entry["launch_attempted"] = True
            entry["launch_ok"] = launch_result["ok"]
            if launch_result["error"]:
                entry["launch_error"] = launch_result["error"]
            # Re-check running after launch
            entry["running"] = _running(b["name"])
            if entry["running"]:
                entry["chat_based_interaction"] = True
        results.append(entry)
    return results


def main() -> int:
    auto_start = "--auto-start" in sys.argv
    results = check_browsers(auto_start=auto_start)
    available = [r for r in results if r["installed"] and r["running"]]
    print(json.dumps({
        "browsers": results,
        "any_available": bool(available),
        "chat_based_interaction_available": any(r["chat_based_interaction"] for r in results),
    }, indent=2))
    if not available:
        installed = [r["display_name"] for r in results if r["installed"]]
        if installed:
            print(f"\nBrowsers installed but not running: {', '.join(installed)}")
            print("Run with --auto-start to attempt launch, or launch manually:")
            for r in results:
                if r["installed"] and not r["running"]:
                    print(f"  {r['launch_cmd']}")
        else:
            print("\nNo agentic browser (Neo/Ego) installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
