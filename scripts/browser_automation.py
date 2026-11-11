#!/usr/bin/env python3
"""Browser automation for agent-router — attempts system control of Neo/Ego.

Attempts to launch and interact with BrowserClaw (BrowserOS neo) or ego lite
via AppleScript / open commands. Goal: open Gemini for deep research via
chat-based interaction, controlled by the system — not manual.

Never installs anything. Graceful degradation: if browser can't be controlled,
returns text-only fallback.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

APPLESCRIPT_TEMPLATE = '''
tell application "{app_name}"
    activate
    delay 1
    tell front window
        try
            execute javascript "{js}"
        end try
    end tell
end tell
'''


def _running(name: str) -> bool:
    try:
        out = subprocess.run(["pgrep", "-ax", name],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return bool(out)
    except Exception:
        return False


def _launch(name: str) -> dict:
    try:
        subprocess.run(["open", "-a", name], capture_output=True, text=True, timeout=10)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _applescript(app_name: str, js: str) -> dict:
    script = APPLESCRIPT_TEMPLATE.format(app_name=app_name, js=js.replace('"', '\\"'))
    try:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=15)
        return {"ok": out.returncode == 0, "output": out.stdout.strip(), "error": out.stderr.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def open_gemini(app_name: str, research_topic: str) -> dict:
    """Attempt to open Gemini in the given browser for deep research."""
    # First ensure running
    if not _running(app_name):
        launch = _launch(app_name)
        if not launch["ok"]:
            return {"ok": False, "error": f"Failed to launch {app_name}: {launch.get('error')}"}
        # wait a moment for app to open
        import time
        time.sleep(2)

    # Try to navigate to Gemini via AppleScript JS injection
    js = f"""
        var w = window.open('https://gemini.google.com/app', '_blank');
        if (w) {{ w.focus(); }}
    """
    result = _applescript(app_name, js)
    if result["ok"]:
        return {
            "ok": True,
            "browser": app_name,
            "action": "opened_gemini",
            "topic": research_topic,
            "note": "Gemini opened in browser. Deep research via chat-based interaction.",
        }
    return {
        "ok": False,
        "browser": app_name,
        "error": result.get("error", "AppleScript execution failed"),
        "fallback": "text-only research via NIM/skills",
    }


def try_browsers(research_topic: str, auto_start: bool = False) -> List[dict]:
    """Try BrowserClaw then ego lite. Return results for each attempt."""
    results: List[dict] = []
    for app in ["BrowserClaw", "ego lite"]:
        if not _running(app) and not _installed(app):
            continue
        r = open_gemini(app, research_topic)
        results.append(r)
        if r["ok"]:
            break  # success, no need to try the other
    return results


def _installed(name: str) -> bool:
    try:
        out = subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == 'com.browseros.BrowserClaw' OR kMDItemCFBundleIdentifier == 'com.citrolabs.ego.lite'"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return bool(out)
    except Exception:
        return False


def main() -> int:
    auto_start = "--auto-start" in sys.argv
    topic = "deep research task"
    for a in sys.argv[1:]:
        if not a.startswith("--"):
            topic = a
            break
    results = try_browsers(topic, auto_start=auto_start)
    ok = any(r["ok"] for r in results)
    print(json.dumps({
        "topic": topic,
        "any_ok": ok,
        "attempts": results,
        "fallback": "text-only research via NIM/skills" if not ok else None,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
