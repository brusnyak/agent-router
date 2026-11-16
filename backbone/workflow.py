"""Workflow DAG: fan-out/fan-in orchestration over lanes/workers.

A Workflow decomposes a goal into ordered/parallel sub-tasks, assigns each to a
worker/lane, runs each through the router, gates each step, and optionally
synthesizes results. Steps declare dependencies; independent steps (fan-out)
run in parallel. A step whose gate fails marks itself failed and its
dependents are skipped. Results are collected per step and optionally combined
by a synthesize worker.

Grammar: `backbone workflow <workflow-id> "<prompt>"`
"""
from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed



@dataclass
class WorkflowStep:
    id: str
    worker: str
    gate: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    id: str
    description: str
    steps: List[WorkflowStep]
    fan_out: List[str] = field(default_factory=list)
    synthesize: Optional[str] = None


@dataclass
class StepResult:
    id: str
    ok: bool
    worker: str
    output: str
    gate_passed: bool
    error: Optional[str] = None


@dataclass
class WorkflowResult:
    workflow_id: str
    step_results: Dict[str, StepResult]
    synthesis: Optional[str]
    ok: bool


def load_workflows(path: str) -> Dict[str, Workflow]:
    """Load workflow definitions from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    workflows: Dict[str, Workflow] = {}
    for w in data.get("workflows", []):
        steps = [
            WorkflowStep(
                id=s["id"],
                worker=s["worker"],
                gate=s.get("gate"),
                depends_on=list(s.get("depends_on", [])),
            )
            for s in w.get("steps", [])
        ]
        workflows[w["id"]] = Workflow(
            id=w["id"],
            description=w.get("description", ""),
            steps=steps,
            fan_out=list(w.get("fan_out", [])),
            synthesize=w.get("synthesize"),
        )
    return workflows


def _topo_order(steps: List[WorkflowStep]) -> List[str]:
    """Return step ids in dependency order (dependents after dependencies)."""
    by_id = {s.id: s for s in steps}
    order: List[str] = []
    visited: Dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(sid: str, stack: List[str]) -> None:
        if visited.get(sid) == 1:
            return
        if sid in stack:
            raise ValueError(f"cycle detected at {sid}")
        stack.append(sid)
        for dep in by_id[sid].depends_on:
            if dep not in by_id:
                raise ValueError(f"step {sid} depends on unknown step {dep}")
            visit(dep, stack)
        stack.pop()
        visited[sid] = 1
        order.append(sid)

    for s in steps:
        visit(s.id, [])
    return order


def _eligible_steps(
    order: List[str],
    step_results: Dict[str, StepResult],
    steps: List[WorkflowStep],
    fan_out: set,
) -> List[str]:
    """Return step ids whose dependencies are all satisfied (done or skipped-failed)."""
    by_id = {s.id: s for s in steps}
    eligible: List[str] = []
    for sid in order:
        if sid in step_results:
            continue  # already dispatched
        deps = by_id[sid].depends_on
        # A step is eligible if every dependency either passed (ok+gate) or
        # failed (so this step is skipped because its input is missing).
        all_deps_resolved = all(d in step_results for d in deps)
        if not all_deps_resolved:
            continue
        # If any dependency failed (gate not passed), skip this step.
        any_dep_failed = any(
            not step_results[d].ok or not step_results[d].gate_passed for d in deps
        )
        if any_dep_failed:
            step_results[sid] = StepResult(
                id=sid,
                ok=False,
                worker=by_id[sid].worker,
                output="",
                gate_passed=False,
                error=f"skipped: dependency {' '.join(d for d in deps if not step_results[d].ok or not step_results[d].gate_passed)} failed",
            )
            continue
        eligible.append(sid)
    return eligible


def run_workflow(
    bb: Any,
    workflow_id: str,
    prompt: str,
    cwd: str,
    read_only: bool = False,
    workflows_path: str = "config/workflows.yaml",
) -> WorkflowResult:
    """Execute a workflow DAG over lanes/workers.

    Each step runs through `bb._dispatch(worker, step_prompt, cwd, read_only,
    attempt)` then its gate (if any). Independent steps fan out in parallel.
    Returns WorkflowResult with per-step results and optional synthesis.
    """
    import os

    workflows_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), workflows_path)
    if not os.path.exists(workflows_path):
        workflows_path = os.path.join(os.getcwd(), workflows_path)
    workflows = load_workflows(workflows_path)
    if workflow_id not in workflows:
        return WorkflowResult(
            workflow_id=workflow_id,
            step_results={},
            synthesis=None,
            ok=False,
        )
    wf = workflows[workflow_id]

    by_id = {s.id: s for s in wf.steps}
    order = _topo_order(wf.steps)
    fan_out = set(wf.fan_out)
    step_results: Dict[str, StepResult] = {}
    dispatched: set = set()

    def step_prompt(sid: str) -> str:
        s = by_id[sid]
        return (
            f"Workflow: {wf.description}\n"
            f"Original goal: {prompt}\n"
            f"Your step ({sid}): {s.worker} — {s.id}\n"
            f"Produce the output for this step only. Keep it concise and gate-checkable."
        )

    def run_one(sid: str) -> StepResult:
        s = by_id[sid]
        from .core import norm_worker
        worker = norm_worker(s.worker)
        r = bb._dispatch(worker, step_prompt(sid), cwd, read_only, attempt=1)
        output = r.text or ""
        # Persist step output so gates can inspect it without shell injection.
        out_path = os.path.join(cwd, f".wf-{wf.id}-{sid}.out")
        try:
            with open(out_path, "w") as fh:
                fh.write(output)
        except OSError:
            out_path = ""
        gate_passed = False
        gate_out = ""
        if r.ok and s.gate:
            from .workspace import run_gate

            gate_cmd = s.gate.replace("<output-file>", out_path).replace("<output>", output)
            gate_passed, gate_out = run_gate(gate_cmd, cwd)
        ok = r.ok and (gate_passed if s.gate else True)
        return StepResult(
            id=sid,
            ok=ok,
            worker=worker,
            output=output,
            gate_passed=gate_passed,
            error=None if ok else (r.text or "gate failed" if s.gate else "worker error"),
        )

    max_rounds = len(order) + 1
    for _ in range(max_rounds):
        eligible = _eligible_steps(order, step_results, wf.steps, fan_out)
        to_dispatch = [sid for sid in eligible if sid not in dispatched]
        if not to_dispatch:
            break
        # Parallel for fan-out steps, sequential otherwise.
        parallel = [sid for sid in to_dispatch if sid in fan_out]
        sequential = [sid for sid in to_dispatch if sid not in fan_out]
        for sid in sequential:
            step_results[sid] = run_one(sid)
            dispatched.add(sid)
        if parallel:
            with ThreadPoolExecutor(max_workers=len(parallel)) as ex:
                futures = {ex.submit(run_one, sid): sid for sid in parallel}
                for fut in as_completed(futures):
                    sid = futures[fut]
                    step_results[sid] = fut.result()
                    dispatched.add(sid)

    # Determine overall ok: all steps that were eligible (not skipped) passed.
    all_ok = all(sr.ok and sr.gate_passed for sr in step_results.values())

    # Synthesis
    synthesis: Optional[str] = None
    if wf.synthesize and all_ok:
        inputs = "\n\n".join(
            f"## Step {sid} ({sr.worker})\n{sr.output}"
            for sid, sr in step_results.items()
            if sr.ok
        )
        synth_prompt = (
            f"Workflow: {wf.description}\n"
            f"Original goal: {prompt}\n"
            f"Synthesize the results of the completed steps below into a single "
            f"coherent answer. Keep per-step evidence concise and attribute each "
            f"claim to its step id.\n\n{inputs}"
        )
        from .core import norm_worker
        r = bb._dispatch(norm_worker(wf.synthesize), synth_prompt, cwd, read_only, attempt=1)
        synthesis = r.text if r.ok else None
        if not r.ok:
            all_ok = False

    return WorkflowResult(
        workflow_id=workflow_id,
        step_results=step_results,
        synthesis=synthesis,
        ok=all_ok,
    )
