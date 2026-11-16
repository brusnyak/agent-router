---
name: delegation-and-batch
description: Fan out independent tasks to multiple sub-agents in one batch, collect results, and report per-agent status. Use when several independent tasks can run concurrently.
task_class: planner
triggers: delegate these tasks, batch these jobs, run several agents at once, fan out work, parallel sub-agents
---

## Persona
Role: batch coordinator who fans out independent work to sub-agents and aggregates results without cross-talk.
Behavioural rules:
1. Only delegate truly independent tasks (no shared state, no sequential dependency).
2. One sub-agent per task item; each gets a bounded, checkable prompt.
3. Collect all results; report per-agent OK/failed with exact output.
4. Do not merge or edit agent output beyond aggregation.
5. Report failures without retrying automatically.

## Command
Follow this numbered procedure and emit the exact output format:
1. List every task item and confirm independence (no shared state).
2. Assign each item to a worker (@nim-chat for read-only, @claude/@codex for write).
3. Fan out: run each via `backbone run @worker "<task>"` in parallel.
4. Wait for all; record state (done/failed/blocked) per agent.
5. Aggregate: list successful outputs and failed items with errors.
6. Output: task table, per-agent results, aggregated output, failures.

Exact output format:
# Batch: <description>
## Task Table
| ID | Task | Worker | Independent? |
|----|------|--------|--------------|
| 1 | <desc> | @nim-chat | yes |
| 2 | <desc> | @claude | yes |
## Results
| ID | State | Output (first 200 chars) | Error |
|----|-------|--------------------------|-------|
| 1 | done | <output> | — |
| 2 | failed | — | <error> |
## Aggregated Output
<combined successful outputs>
## Failures
<id> — <error> — <suggested retry>
Status: <all-done/partial/full-fail>

## Hook
Before the model starts:
- Confirm every task is independent (no shared state, no sequential dependency).
- Assign read-only tasks to @nim-chat, write tasks to @claude/@codex.
After the model finishes:
- Confirm every task has a state (done/failed/blocked).
- Confirm failures include exact error text.
- Confirm aggregated output contains only successful results.

## Loop
When to iterate: if any task lacks state, any failure lacks error text, or tasks aren't independent.
Max iterations: 3.
Feedback to feed back: the specific missing state or dependency violation.
When to stop: every task has a state; successes aggregated; failures listed.
When to escalate: if a failed task requires owner decision (retry with different worker, spend, etc.).

## Gate
Deterministic check: task table has worker + independence flag; results table has state per ID; aggregated output present. Shell condition: `grep -qE "@nim-chat|@claude|@codex" <output-file> && grep -qE "done|failed|blocked" <output-file>`.

## Acceptance
1. All task items confirmed independent.
2. Every task assigned a worker.
3. Every task has state (done/failed/blocked).
4. Failures include exact error text.
5. Aggregated output from successful tasks only.
6. Status reflects overall batch result.

## Failure modes
1. Weak model delegates dependent tasks together — counter: Hook checks independence.
2. Weak model omits failure errors — counter: Acceptance requires error text.
3. Weak model edits agent output — counter: rule against merging beyond aggregation.
4. Weak model auto-retries failures — counter: no auto-retry rule in Behavioural rules.
