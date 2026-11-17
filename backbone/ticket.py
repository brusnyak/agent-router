"""Vault ticket adapter: parse allowlisted tickets from pages/jobs/ and submit
them once to Backbone's existing SQLite queue (idempotent by ticket_id).

No DONE_CMD execution, no raw shell gates, no new queue/database/scheduler.
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional

import yaml

from .jobs import Jobs
from .db import connect

REQUIRED_FIELDS = {"ticket_id", "status", "execution_authority", "goal", "acceptance",
                   "project", "allowed_paths", "data_class", "budget", "timeout",
                   "gate_name"}
ALLOWED_STATUSES = {"ready", "running", "verify", "accepted", "blocked"}
ALLOWED_AUTHORITY = {"preauthorized-internal", "owner-approval-required"}
ALLOWED_DATA_CLASS = {"public", "sanitized", "private-local"}
MAX_BUDGET_S = 3600  # hard ceiling so no ticket can run longer than the existing cap
MAX_TIMEOUT_S = 3600

# YAML frontmatter block: leading `---` ... `---`
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


class TicketError(Exception):
    pass


def _parse_ticket(text: str) -> dict:
    m = _FRONTMATTER.match(text)
    if not m:
        raise TicketError("no YAML frontmatter block (--- ... ---)")
    data = yaml.safe_load(m.group(1)) or {}
    if not isinstance(data, dict):
        raise TicketError("frontmatter is not a mapping")
    missing = REQUIRED_FIELDS - set(data)
    if missing:
        raise TicketError(f"missing fields: {sorted(missing)}")
    if data["status"] not in ALLOWED_STATUSES:
        raise TicketError(f"invalid status {data['status']!r}")
    if data["execution_authority"] not in ALLOWED_AUTHORITY:
        raise TicketError(f"invalid execution_authority {data['execution_authority']!r}")
    if data["data_class"] not in ALLOWED_DATA_CLASS:
        raise TicketError(f"invalid data_class {data['data_class']!r}")
    # budget/timeout must be ints within the existing cap
    try:
        data["budget"] = int(data["budget"])
        data["timeout"] = int(data["timeout"])
    except (TypeError, ValueError):
        raise TicketError("budget and timeout must be integers")
    if data["budget"] <= 0 or data["budget"] > MAX_BUDGET_S:
        raise TicketError(f"budget {data['budget']} outside (0, {MAX_BUDGET_S}]")
    if data["timeout"] <= 0 or data["timeout"] > MAX_TIMEOUT_S:
        raise TicketError(f"timeout {data['timeout']} outside (0, {MAX_TIMEOUT_S}]")
    return data


def find_tickets(jobs_dir: str) -> List[dict]:
    """Scan a local synchronized vault pages/jobs/ working tree for valid tickets.

    Returns (ticket_dict, source_path) pairs; invalid files are skipped with a
    note and never submitted. Reads only — never writes to the vault tree.
    """
    out: List[dict] = []
    if not os.path.isdir(jobs_dir):
        return out
    for name in sorted(os.listdir(jobs_dir)):
        path = os.path.join(jobs_dir, name)
        if not os.path.isfile(path) or not name.endswith(".md"):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        try:
            data = _parse_ticket(text)
        except TicketError as e:
            out.append({"ticket_id": name, "_error": str(e), "_path": path,
                        "_skipped": True})
            continue
        data["_path"] = path
        out.append(data)
    return out


def submit_tickets(jobs_dir: str, bb) -> List[dict]:
    """Submit each eligible ticket exactly once to the existing SQLite queue.

    Eligible: status == 'ready', execution_authority == 'preauthorized-internal',
    valid schema, not already queued under the same ticket_id.
    Returns a list of per-ticket result dicts.
    """
    results: List[dict] = []
    jobs = Jobs(bb)
    existing = set()
    try:
        import json as _j
        for r in bb.con.execute("SELECT opts FROM jobs").fetchall():
            o = _j.loads(r[0] or "{}")
            if o.get("ticket_id"):
                existing.add(o["ticket_id"])
    except Exception:
        pass
    for t in find_tickets(jobs_dir):
        tid = t.get("ticket_id", "")
        if t.get("_skipped"):
            results.append({"ticket_id": tid, "submitted": False,
                            "reason": f"invalid ticket: {t.get('_error')}",
                            "path": t.get("_path")})
            continue
        if tid in existing:
            results.append({"ticket_id": tid, "submitted": False,
                            "reason": "duplicate ticket_id already queued",
                            "path": t.get("_path")})
            continue
        if t["status"] != "ready":
            results.append({"ticket_id": tid, "submitted": False,
                            "reason": f"status {t['status']} != ready",
                            "path": t.get("_path")})
            continue
        if t["execution_authority"] != "preauthorized-internal":
            results.append({"ticket_id": tid, "submitted": False,
                            "reason": f"authority {t['execution_authority']} requires owner approval",
                            "path": t.get("_path")})
            continue
        # named gate must exist in config; raw shell gates are never accepted
        gate = t["gate_name"]
        try:
            bb.named_gate(gate)
        except PermissionError as e:
            results.append({"ticket_id": tid, "submitted": False,
                            "reason": f"gate {gate}: {e}", "path": t.get("_path")})
            continue
        text = f"/{t.get('goal','')} --gate {gate} --worker {t.get('worker','')} --timeout {t['timeout']}"
        opts = {"ticket_id": tid, "source": t.get("_path"),
                "project": t.get("project", ""), "allowed_paths": t.get("allowed_paths", []),
                "data_class": t.get("data_class", ""), "budget": t.get("budget", 0),
                "timeout": t.get("timeout", 0), "read_only": t.get("data_class") != "private-local",
                "side_effects": t.get("side_effects", []), "acceptance": t.get("acceptance", "")}
        jid = jobs.submit(text, **opts)
        existing.add(tid)
        results.append({"ticket_id": tid, "submitted": True, "job_id": jid,
                        "path": t.get("_path")})
    return results
