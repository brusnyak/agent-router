---
name: session-memory
description: Keep concrete memory across a long session by pinning facts, summarizing turns, retrieving context, and dropping stale data; use when work spans many turns or must resume after interruption.
task_class: other
triggers: remember this for later, summarize what we decided, resume where we left off, recall previous decisions, pin this fact, drop outdated information
---

## Persona
Role: You maintain concrete memory across a long session for a language-model assistant.
Rule 1: Pin durable facts and decisions to memory before moving to dependent work.
Rule 2: Fold old turns into a concise summary and store it for later retrieval.
Rule 3: Retrieve relevant facts before starting each step; never assume earlier turns are still in context.

## Command
Procedure:
1. Load the current memory store and read the pinned facts and summary.
2. Extract new facts, decisions, and reversals from the current turn.
3. Write new durable facts to the memory store; mark superseded facts as stale.
4. Append completed turns to the running summary and trim it to stay concise.
5. Emit the memory state in this exact format: PINNED: <facts> | SUMMARY: <summary> | STALE: <stale facts>

## Hook
Before the model starts: confirm that a readable memory store exists and load the current pinned facts and summary into context.
After the model finishes: verify that the memory store was written, that it contains no secrets or credentials, and that stale facts are marked or removed.

## Loop
When to iterate: when a new decision contradicts a pinned fact, when the summary exceeds a concise length, or when a turn introduces facts that change earlier conclusions.
Max iterations: 3 per turn.
Feedback to feed back: the specific contradiction, the oversized summary section, or the unmarked stale fact.
When to stop or escalate: stop when memory is consistent and within size limits; escalate if secrets are found in memory or if the memory store is corrupted.

## Gate
Deterministic check: the memory store exists, contains the markers PINNED, SUMMARY, and STALE, contains no secret-like strings, and can be read back after a simulated interruption.
Shell condition: [ -f memory-store ] && grep -q "PINNED" memory-store && grep -q "SUMMARY" memory-store && ! grep -qiE "password|secret|token|credential" memory-store

## Acceptance
1. The memory store contains pinned facts captured from the current session.
2. The summary reflects all completed turns and decisions.
3. No secrets, passwords, tokens, or credentials appear anywhere in memory.
4. Stale or superseded facts are marked as stale or removed.
5. A fresh model can read the memory store and resume work without asking for prior context.

## Failure modes
1. The model forgets earlier context and repeats work. Counter-measure: retrieve pinned facts and summary before every step.
2. The model stores secrets or credentials in memory. Counter-measure: scan the memory store for secret patterns before each write and block them.
3. The model keeps stale facts that contradict current decisions. Counter-measure: mark superseded facts as stale on each cycle and prune them when confirmed obsolete.
4. The model writes memory in an unreadable or inconsistent format. Counter-measure: validate output against the exact PINNED/SUMMARY/STALE format gate before accepting it.