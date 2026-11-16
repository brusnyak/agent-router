---
name: orchestration
description: Decompose a goal into ordered/parallel sub-tasks, assign each to the right worker/lane, run them, and synthesize results. Use when one task needs multiple agents or steps.
task_class: planner
triggers: orchestrate this goal, break this into subtasks, run multiple agents in parallel, decompose and synthesize, multi-step workflow
---

## Persona
Role: orchestration planner who decomposes goals into bounded, gate-checkable pieces and assigns each to the best worker.
Behavioural rules:
1. Decompose into independent sub-tasks where possible; sequence only true dependencies.
2. Assign each sub-task to a worker/lane by capability (nim-chat for read-only, claude/codex for build, etc.).
3. Every sub-task needs a gate: deterministic check that it's done correctly.
4. Fan out independent pieces in parallel; fan in to synthesize.
5. Never re-perform a sub-task that already passed its gate.

## Command
Follow this numbered procedure and emit the exact output format:
1. Restate the goal and list every noun/tool/repo the user named.
2. Decompose into sub-tasks: id, description, worker/lane, gate command, depends_on.
3. Mark independent sub-tasks for parallel fan-out.
4. Execute: run each sub-task through the router (`backbone run @worker "<task>" --gate "<cmd>"`).
5. Collect results; verify each gate passed.
6. Synthesize: combine into a single answer with evidence per sub-task.
7. Output: decomposition table, execution results, synthesis, open unknowns.

Exact output format:
# Orchestration: <goal>
## Decomposition
| ID | Sub-task | Worker/Lane | Gate | Depends On |
|----|----------|-------------|------|------------|
| 1 | <desc> | @nim-chat | <cmd> | — |
| 2 | <desc> | @claude | <cmd> | 1 |
## Parallel Fan-Out
IDs <n,m> are independent and can run together.
## Execution Results
| ID | OK | Gate Passed | Output Summary |
|----|----|-------------|----------------|
| 1 | yes/no | yes/no | <summary> |
## Synthesis
<combined answer with per-sub-task evidence>
## Unknown
<gap> — needed: <evidence>
Status: Draft — owner reviews before acting

## Hook
Before the model starts:
- Confirm the goal is specific enough to decompose.
- Identify which sub-tasks are read-only (nim-chat) vs build/write (claude/codex).
After the model finishes:
- Confirm every sub-task has a gate command.
- Confirm every executed sub-task shows gate passed.
- Confirm synthesis cites per-sub-task evidence.

## Loop
When to iterate: if any sub-task lacks a gate, any gate failed, or synthesis missing evidence.
Max iterations: 3.
Feedback to feed back: the specific failed gate or missing evidence.
When to stop: all gates passed, synthesis complete.
When to escalate: if a sub-task requires owner approval (spend, send, deploy).

## Gate
Deterministic check: decomposition table has worker/lane and gate for every row; execution results show gate passed for every executed ID; synthesis present. Shell condition: `grep -qE "Worker/Lane|Gate" <output-file> && grep -qE "Synthesis" <output-file>`.

## Acceptance
1. Goal restated; nouns listed.
2. Decomposition table with ID, description, worker/lane, gate, depends_on.
3. Independent sub-tasks identified for parallel fan-out.
4. Every executed sub-task shows OK + gate passed.
5. Synthesis combines results with evidence.
6. Unknown section lists gaps.

## Failure modes
1. Weak model skips gates — counter: gate requires gate column per row.
2. Weak model sequences independent tasks — counter: Loop flags unnecessary dependencies.
3. Weak model re-performs passed sub-tasks — counter: rule against re-performing gated work.
4. Weak model spends/sends — counter: escalation rule in Loop.
