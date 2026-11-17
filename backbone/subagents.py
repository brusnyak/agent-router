"""Subagents: bounded workers the router creates for one task, then reaps.

A subagent = worker (pi/nim-chat/claude/codex/...) + tool allowlist + isolated
workspace + gate + budget (tokens/time/cost). It runs one task end-to-end, writes
its patch to the run table, and dies. No persistent state beyond the run.

Smart-lazy: reuses backbone.workers (PiWorker, ClaudeWorker, CodexWorker, ...),
backbone.workspace (isolated worktree), backbone.graph (gate loop), and the existing
KeyPool for NIM key budgeting. Nothing new is invented — only composed.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import otel
from .db import DB
from .workers import (PiWorker, NimCallWorker, ClaudeWorker, CodexWorker,
                      Result)
from .adapter import GenericWorker
from .workspace import IsolationError, Workspace, run_gate

# Worker classes keyed by the spec prefix used in backbone/core.py dispatch.
_WORKER_BY_KIND: Dict[str, type] = {
    "pi": PiWorker,
    "nim-chat": NimCallWorker,
    "claude": ClaudeWorker,
    "codex": CodexWorker,
    "generic": GenericWorker,
}


@dataclass
class SubagentSpec:
    """One bounded subagent: what it may touch, how it's judged, when it stops."""
    kind: str              # pi / nim-chat / claude / codex / generic / ...
    tool_allowlist: List[str] = field(default_factory=list)  # e.g. ["read"] for read-only
    gate: str = ""         # acceptance command (exit 0 = pass); "" = no gate
    budget_tokens: int = 0 # soft token cap; 0 = unconstrained
    budget_ms: int = 0     # soft wall-clock cap ms; 0 = unconstrained
    budget_cost: float = 0.0  # soft cost cap; 0 = unconstrained
    project: str = ""      # registered project id for cwd/allowed_roots
    read_only: bool = False


@dataclass
class SubagentResult:
    id: str
    state: str           # queued | running | done | blocked | failed
    worker: str
    output: str = ""
    patch: str = ""
    gate_passed: bool = False
    verified: bool = False
    latency_ms: int = 0
    error: str = ""
    ticket: str = ""


class SubagentRunner:
    """Spawn, supervise, reap one bounded subagent per task."""

    def __init__(self, bb) -> None:
        self.bb = bb
        self.con: DB = bb.con
        self.work_root = bb.work_root
        self.pool: KeyPool = bb.pool
        self.nim_model = bb.cfg["nim"]["model"]
        self.workers_cfg = bb.cfg.get("workers", {})

    # -- lifecycle -------------------------------------------------------
    def create(self, spec: SubagentSpec, prompt: str, run_id: str) -> str:
        """Register a subagent row; returns its id."""
        sid = uuid.uuid4().hex[:10]
        try:
            self.con.execute(
                "INSERT INTO subagents (id, run_id, worker, tools, gate, budget_tokens, budget_ms, budget_cost, state) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')",
                (sid, run_id, spec.kind, ",".join(spec.tool_allowlist), spec.gate,
                 spec.budget_tokens, spec.budget_ms, spec.budget_cost))
            self.con.commit()
        except Exception:
            # table may not exist yet on old DBs; migrate lazily
            try:
                self.con.execute("CREATE TABLE IF NOT EXISTS subagents("
                                 "id TEXT PRIMARY KEY, run_id TEXT NOT NULL, worker TEXT, tools TEXT DEFAULT '',"
                                 " gate TEXT, budget_tokens INTEGER DEFAULT 0, budget_ms INTEGER DEFAULT 0,"
                                 " budget_cost REAL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued',"
                                 " created REAL DEFAULT (strftime('%s','now')), finished REAL,"
                                 " evidence TEXT DEFAULT '', error TEXT DEFAULT '')")
                self.con.execute(
                    "INSERT INTO subagents (id, run_id, worker, tools, gate, budget_tokens, budget_ms, budget_cost, state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')",
                    (sid, run_id, spec.kind, ",".join(spec.tool_allowlist), spec.gate,
                     spec.budget_tokens, spec.budget_ms, spec.budget_cost))
                self.con.commit()
            except Exception:
                pass
        return sid

    def run(self, sid: str, spec: SubagentSpec, prompt: str, run_id: str) -> SubagentResult:
        """Execute one bounded subagent: workspace -> worker -> gate -> verify -> patch."""
        t0 = time.time()
        state = SubagentResult(id=sid, state="running", worker=spec.kind)
        self._set_state(sid, "running")

        # isolated workspace (fail closed if not a git repo and isolate required)
        proj_path = self.bb.project_path(spec.project, None) if spec.project else os.getcwd()
        try:
            ws = Workspace(proj_path, sid, self.work_root,
                           isolate=True and not spec.read_only)
        except IsolationError as e:
            state.state = "failed"
            state.error = str(e)
            self._finish(sid, state, t0)
            return state

        try:
            with otel.span("router.subagent.work", {"subagent.id": sid, "subagent.kind": spec.kind}):
                # build worker on the fly (smart-lazy: reuse existing worker classes)
                worker_cls = _WORKER_BY_KIND.get(spec.kind.split(":")[0])
                if worker_cls is None:
                    raise ValueError(f"unknown subagent kind '{spec.kind}'")

                base_kind = spec.kind.split(":")[0]
                if base_kind == "pi":
                    worker = PiWorker(self.workers_cfg.get("pi", {}), self.nim_model)
                    r = worker.run(prompt, ws.path, self.pool,
                                   prefer=spec.kind.split(":")[1] if ":" in spec.kind else None,
                                   system=self._system_prompt(spec),
                                   read_only=spec.read_only or bool(spec.tool_allowlist and "write" not in spec.tool_allowlist))
                elif base_kind == "nim-chat":
                    worker = NimCallWorker(self.workers_cfg.get("nim-chat", {}), self.nim_model)
                    r = worker.run(prompt, ws.path, key=self.pool.value(self.pool.names[0] if self.pool.names else "NIM_1"),
                                   read_only=spec.read_only, pool=self.pool)
                elif base_kind == "claude":
                    worker = ClaudeWorker(self.workers_cfg.get("claude", {}))
                    r = worker.run(prompt, ws.path, read_only=spec.read_only)
                elif base_kind == "codex":
                    worker = CodexWorker(self.workers_cfg.get("codex", {}))
                    r = worker.run(prompt, ws.path, read_only=spec.read_only)
                else:
                    worker = GenericWorker(self.workers_cfg.get("generic", {}).get("cmd", ""),
                                           set(self.workers_cfg.get("generic", {}).get("allowlist", [])))
                    r = worker.run(prompt, ws.path, read_only=spec.read_only)

                state.latency_ms = int((time.time() - t0) * 1000)
                if not r.ok:
                    state.state = "blocked"
                    state.error = r.text or "worker error"
                    self._finish(sid, state, t0)
                    return state

                # gate (acceptance check run by router, never by model)
                gate_passed = True
                gate_out = ""
                if spec.gate:
                    gate_passed, gate_out = run_gate(spec.gate, ws.path)
                    state.gate_passed = gate_passed
                    if not gate_passed:
                        state.state = "blocked"
                        state.error = f"gate failed: {gate_out[-800:]}"
                        self._finish(sid, state, t0)
                        return state

                # web + file verification (routecheck-style)
                from .verify import verify_output
                evidence_ok, vreasons = verify_output(r.text, [ws.path, proj_path])
                state.verified = gate_passed and evidence_ok
                if not evidence_ok:
                    state.state = "blocked"
                    state.error = "; ".join(vreasons[:3]) if vreasons else "evidence_unverified"
                    self._finish(sid, state, t0)
                    return state

                state.state = "done"
                state.output = r.text
                state.worker = r.worker or spec.kind
                state.patch = ws.diff() if ws.isolated else ""
        except Exception as e:  # any failure -> blocked with a ticket, never silently dropped
            state.state = "failed"
            state.error = f"{type(e).__name__}: {e}"
            state.latency_ms = int((time.time() - t0) * 1000)
        finally:
            try:
                ws.cleanup()
            except Exception:
                pass

        self._finish(sid, state, t0)
        return state

    # -- persistence ----------------------------------------------------
    def _system_prompt(self, spec: SubagentSpec) -> str:
        parts = ["You are a bounded subagent created by the agent router for one task only."]
        if spec.tool_allowlist:
            parts.append("Allowed tools: " + ", ".join(spec.tool_allowlist) + ". Do not use any other tool.")
        if spec.read_only:
            parts.append("Read-only: do not write, edit, or delete anything.")
        if spec.budget_tokens:
            parts.append(f"Token budget: ~{spec.budget_tokens}. Stay concise.")
        if spec.gate:
            parts.append(f"Your work must pass: {spec.gate}.")
        return " ".join(parts)

    def _set_state(self, sid: str, state: str) -> None:
        try:
            self.con.execute("UPDATE subagents SET state=? WHERE id=?", (state, sid))
            self.con.commit()
        except Exception:
            pass

    def _finish(self, sid: str, state: SubagentResult, t0: float) -> None:
        state.latency_ms = int((time.time() - t0) * 1000)
        try:
            self.con.execute(
                "UPDATE subagents SET state=?, finished=?, evidence=?, error=? WHERE id=?",
                (state.state, time.time(), state.output[:4000], state.error[:4000], sid))
            self.con.commit()
        except Exception:
            pass


def delegate(bb, spec: SubagentSpec, prompt: str, run_id: str) -> SubagentResult:
    """Convenience: create + run one bounded subagent. Used by backbone delegate and swarm."""
    runner = SubagentRunner(bb)
    sid = runner.create(spec, prompt, run_id)
    return runner.run(sid, spec, prompt, run_id)
