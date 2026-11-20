"""Idle tick: submit the next backlog item when the router has been idle.

Config: `idle_minutes` (default 10). Backlog: `~/.agent-router/backlog.jsonl`,
one JSON task per line: {prompt, gate, worker_hint, runner}. Items with
`runner: mac` are addressed to `@node:mac`. Honours `~/memory-vault/pages/dispatch-PAUSE`.
Idempotent (a submitted line is consumed from the backlog) and flock-safe (a lock
serializes concurrent ticks).

Routing: free workers first (NIM / pi / kilo / cline / opencode via worker_hint);
items with runner: mac go to @node:mac. Escalation to codex then claude after two
failed gates is handled by the hub daemon retrying failed jobs; idle_tick only
picks the initial worker.
"""
from __future__ import annotations

import fcntl
import json
import os
import time

from backbone.core import Backbone, load_config
from backbone.jobs import Jobs

DEFAULT_IDLE_MINUTES = 10
BACKLOG = os.path.expanduser("~/.agent-router/backlog.jsonl")
PAUSE = os.path.expanduser("~/memory-vault/pages/dispatch-PAUSE")
LOCK = os.path.expanduser("~/.agent-router/idle_tick.lock")


def idle_minutes(cfg) -> int:
    try:
        return int((cfg or {}).get("idle_minutes", DEFAULT_IDLE_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES


def paused(pause_file: str = PAUSE) -> bool:
    return os.path.exists(pause_file)


def read_backlog(path: str = BACKLOG) -> list:
    if not os.path.exists(path):
        return []
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def write_backlog(path: str, items: list) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    os.replace(tmp, path)


def running_recently(bb, idle_s: float) -> bool:
    """True if a job is running or started within the idle window."""
    now = time.time()
    for r in bb.con.execute("SELECT state, updated, created FROM jobs"):
        updated = r["updated"] or r["created"] or 0
        if r["state"] == "running" or now - float(updated) < idle_s:
            return True
    return False


def route(item: dict) -> tuple:
    """(text, opts) for submitting this backlog item."""
    text = item.get("prompt", "")
    opts = {}
    hint = (item.get("worker_hint") or "").strip()
    if hint:
        opts["worker"] = hint
    if item.get("gate"):
        opts["gate"] = item["gate"]
    if (item.get("runner") or "").strip() == "mac":
        text = f"@node:mac {text}".strip()
    return text, opts


def tick(cfg=None, *, backlog_path: str = BACKLOG, pause_file: str = PAUSE,
         lock_path: str = LOCK, idle_minutes_override: int | None = None,
         now=None, bb=None) -> dict:
    cfg = cfg or load_config()
    if paused(pause_file):
        return {"state": "paused", "submitted": None}
    if bb is None:
        bb = Backbone(cfg)
    idle_s = (idle_minutes_override if idle_minutes_override is not None
              else idle_minutes(cfg)) * 60
    if running_recently(bb, idle_s):
        return {"state": "active", "submitted": None}
    items = read_backlog(backlog_path)
    if not items:
        return {"state": "empty", "submitted": None}
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"state": "busy", "submitted": None}
        if paused(pause_file):
            return {"state": "paused", "submitted": None}
        if running_recently(bb, idle_s):
            return {"state": "active", "submitted": None}
        items = read_backlog(backlog_path)
        if not items:
            return {"state": "empty", "submitted": None}
        item = items[0]
        text, opts = route(item)
        jid = Jobs(bb).submit(text, **opts)
        write_backlog(backlog_path, items[1:])
        return {"state": "submitted", "job": jid, "item": item}


def main(argv=None) -> int:
    print(json.dumps(tick()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
