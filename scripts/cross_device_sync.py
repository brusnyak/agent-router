#!/usr/bin/env python3
"""Cross-device sync for agent-router.

Syncs kanban.db, vault files, and config between Mac and phone/other devices
via Syncthing (already running per PRODUCT.md). Also provides an optional
SSH tunnel to Oracle VM for council model fan-out research.

Usage:
  python scripts/cross_device_sync.py --status        # check sync health
  python scripts/cross_device_sync.py --council <task>  # fan-out research via Oracle VM council
  python scripts/cross_device_sync.py --export          # export state for phone
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.path.expanduser(os.environ.get("BACKBONE_VAULT", "~/vault"))
DB_PATH = os.path.join(PROJECT_ROOT, "kanban.db")

# Oracle VM council endpoint (via SSH tunnel: ssh -L 3033:127.0.0.1:3033 oracle-vm)
# Defaults to localhost (tunneled). Set ORACLE_VM_HOST for direct IP access.
ORACLE_VM_HOST = os.environ.get("ORACLE_VM_HOST", "localhost")
COUNCIL_PORT = 3033
COUNCIL_URL = f"http://{ORACLE_VM_HOST}:{COUNCIL_PORT}/review/api/council"


def check_syncthing() -> dict:
    """Check Syncthing status via its local API (default port 8384)."""
    result = {"syncthing_running": False, "api_accessible": False, "folders": []}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8384/rest/system/status", timeout=5) as resp:
            body = json.loads(resp.read().decode())
            result["syncthing_running"] = True
            result["api_accessible"] = True
            result["version"] = body.get("version")
    except Exception:
        pass
    return result


def check_files() -> dict:
    """Check that key files exist and are recent."""
    files = {
        "kanban_db": DB_PATH,
        "discovered_inventory": os.path.join(PROJECT_ROOT, "config", "discovered-inventory.json"),
        "index_db": os.path.join(PROJECT_ROOT, "config", "index.db"),
        "config_drift": os.path.join(PROJECT_ROOT, "config", "drift", "config-drift.yaml"),
        "vault_claude_md": os.path.join(VAULT, "CLAUDE.md"),
        "vault_pages": os.path.join(VAULT, "pages"),
    }
    result = {}
    for name, path in files.items():
        p = Path(path)
        if p.exists():
            stat = p.stat()
            result[name] = {
                "exists": True,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
        else:
            result[name] = {"exists": False}
    return result


def council_fan_out(task: str, models: Optional[List[str]] = None) -> dict:
    """Fan-out a research task to Oracle VM council endpoint for multi-model response."""
    if not models:
        models = ["glm", "gemma"]
    payload = {"task": task, "models": models, "synth": True}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        COUNCIL_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Origin": "https://hermes.run.place",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            return {"ok": True, "job_id": body.get("id"), "error": body.get("error")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"Council HTTP {e.code}: {e.read().decode()[:200]}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Council unreachable: {e}. Try: ssh -L 3033:127.0.0.1:3033 oracle-vm"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def council_list() -> dict:
    """List council models and jobs."""
    try:
        with urllib.request.urlopen(COUNCIL_URL, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": f"Council unreachable: {e}"}


def export_state() -> dict:
    """Export agent-router state for cross-device consumption (phone/UI)."""
    export = {
        "exported_at": datetime.now().isoformat(),
        "project_root": PROJECT_ROOT,
        "files": {},
    }
    for name, path in {
        "discovered_inventory": os.path.join(PROJECT_ROOT, "config", "discovered-inventory.json"),
        "config_drift": os.path.join(PROJECT_ROOT, "config", "drift", "config-drift.yaml"),
        "models": os.path.join(PROJECT_ROOT, "config", "models.yaml"),
        "agents": os.path.join(PROJECT_ROOT, "config", "agents.yaml"),
        "lanes": os.path.join(PROJECT_ROOT, "config", "lanes.yaml"),
    }.items():
        p = Path(path)
        if p.exists():
            export["files"][name] = {
                "path": path,
                "size": p.stat().st_size,
            }
    return export


def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-device sync for agent-router")
    ap.add_argument("--status", action="store_true", help="Check Syncthing + file health")
    ap.add_argument("--council", metavar="TASK", help="Fan-out research task to Oracle VM council")
    ap.add_argument("--council-list", action="store_true", help="List council models/jobs")
    ap.add_argument("--export", action="store_true", help="Export state for cross-device consumption")
    args = ap.parse_args()

    if args.status:
        st = check_syncthing()
        files = check_files()
        print(json.dumps({"syncthing": st, "files": files}, indent=2))
        return 0

    if args.council_list:
        result = council_list()
        print(json.dumps(result, indent=2))
        return 0

    if args.council:
        result = council_fan_out(args.council)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.export:
        result = export_state()
        print(json.dumps(result, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
