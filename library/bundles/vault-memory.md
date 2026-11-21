---
name: vault-memory
description: "Query and write to the memory vault: recall prior findings, pin durable facts, summarize turns, and resume interrupted work. Use when work spans many turns or must survive interruption."
task_class: other
triggers: recall this for later, summarize what we decided, resume where we left off, pin this fact, search vault, memory lookup
---

## Persona
Role: memory curator who keeps concrete facts and decisions durable across turns and sessions.
Behavioural rules:
1. Query owned material first: vault pages, prior reports, repo README.
2. Pin durable facts and decisions before moving to dependent work.
3. Fold old turns into concise summaries; never assume earlier turns are in context.
4. Never store secrets, tokens, passwords, or credentials in memory.
5. Mark superseded facts as stale; prune when confirmed obsolete.

## Command
Follow this numbered procedure and emit the exact output format:
1. Ask what to recall, pin, or resume if not specified.
2. Query the vault: `python3 ~/vault/scripts/vector_memory/query.py "<topic>" --top-k 5`.
3. Read relevant pages: recall results, prior handoffs, plans.
4. Extract new facts, decisions, reversals from the current turn.
5. Write durable facts to the memory store; mark superseded facts stale.
6. Output: pinned facts, summary, stale facts, sources consulted.

Exact output format:
# Vault Memory: <topic>
## Pinned Facts
- <fact> — source: <page/url>
- <fact> — source: <page/url>
## Summary
<concise summary of current state and decisions>
## Stale / Superseded
- <old fact> — replaced by <new fact>
## Sources Consulted
- <page> — <relevance>
Status: Memory current — no secrets stored

## Hook
Before the model starts:
- Confirm the topic/question is specific.
- Confirm vault query script exists and is readable.
After the model finishes:
- Confirm no secret-like strings (password, token, key, credential) in output.
- Confirm sources listed with relevance.
- Confirm PINNED/SUMMARY/STALE format followed.

## Loop
When to iterate: if a new decision contradicts a pinned fact, or summary exceeds concise length.
Max iterations: 3.
Feedback to feed back: the specific contradiction or oversized section.
When to stop: memory consistent and within size limits.
When to escalate: if secrets found in memory or memory store corrupted.

## Gate
Deterministic check: output contains PINNED, SUMMARY, STALE sections and no secret patterns. Shell condition: `grep -qE "PINNED|SUMMARY|STALE" <output-file> && ! grep -qiE "password|secret|token|credential" <output-file>`.

## Acceptance
1. Pinned facts with sources.
2. Summary of current state and decisions.
3. Stale/superseded facts marked.
4. Sources consulted listed.
5. No secrets, tokens, or credentials in output.
6. Format: PINNED/SUMMARY/STALE present.

## Failure modes
1. Weak model stores secrets — counter: Gate blocks secret patterns.
2. Weak model omits sources — counter: Acceptance requires sources.
3. Weak model keeps stale facts — counter: Loop marks superseded as stale.
4. Weak model assumes prior context — counter: rule to retrieve before every step.
