"""MCP stdio server: lets OpenCode, Orca, Zed or Claude Code call the backbone as tools.

The chat model (e.g. NIM1 in OpenCode) stays the front door; heavy or multi-worker work is delegated here.
"""
from __future__ import annotations

import json
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from . import library
from .core import Backbone

mcp = FastMCP("agent-router")
_bb: Optional[Backbone] = None


def bb() -> Backbone:
    global _bb
    if _bb is None:
        _bb = Backbone()
    return _bb


@mcp.tool()
def dispatch(prompt: str, project: str = "", worker: str = "", gate: str = "", cwd: str = "", session: str = "") -> str:
    """Run one task. prompt may start with /command #project @worker. gate = NAME of a configured gate (config `gates:`).
    cwd must be inside a registered project or allowed root.
    Returns JSON: run id, state, worker, verified, output, patch path, ticket path."""
    try:
        g = bb().named_gate(gate) if gate else None
        c = bb().check_cwd(cwd) if cwd else None
    except PermissionError as e:
        return json.dumps({"state": "refused", "error": str(e)})
    return json.dumps(bb().run(prompt, project=project, worker=worker, gate=g, cwd=c, session=session or None), default=str)


@mcp.tool()
def submit(prompt: str, project: str = "", worker: str = "", gate: str = "", cwd: str = "") -> str:
    """Queue a task for the background daemon and return its job id immediately (survives disconnects/restarts)."""
    from .jobs import Jobs
    try:
        opts = {k: v for k, v in dict(project=project, worker=worker, gate=bb().named_gate(gate) if gate else "",
                                      cwd=bb().check_cwd(cwd) if cwd else "").items() if v}
    except PermissionError as e:
        return json.dumps({"state": "refused", "error": str(e)})
    return Jobs(bb()).submit(prompt, **opts)


@mcp.tool()
def fanout(prompts: List[str], gate: str = "", cwd: str = "", project: str = "") -> str:
    """Run several independent prompts in parallel, one NIM key each. Returns a JSON list of run results."""
    try:
        g = bb().named_gate(gate) if gate else None
        c = bb().check_cwd(cwd) if cwd else None
    except PermissionError as e:
        return json.dumps({"state": "refused", "error": str(e)})
    return json.dumps(bb().fanout(prompts, gate=g, cwd=c, project=project), default=str)


@mcp.tool()
def library_search(query: str, kind: str = "", k: int = 5) -> str:
    """Search commands, prompts and skills by relevance. kind = command|skill|prompt (optional)."""
    return json.dumps(library.search(bb().con, query, kind or None, k), default=str)


@mcp.tool()
def library_get(name: str, kind: str = "skill") -> str:
    """Return the full body of one library item."""
    row = library.get(bb().con, kind, name)
    return json.dumps(row, default=str) if row else "not found"


@mcp.tool()
def run_status(run_id: str) -> str:
    """State, steps and ticket path of a run."""
    return json.dumps({"run": bb().runs.get(run_id), "steps": bb().runs.steps(run_id)}, default=str)


@mcp.tool()
def keys_status() -> str:
    """Which NIM keys are present, cooling down, and their ok/fail counts."""
    return json.dumps(bb().pool.status())


def serve() -> None:
    mcp.run()
