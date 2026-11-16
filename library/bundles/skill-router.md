---
name: skill-router
description: Match a task to the right skill in the catalog, identify activation gaps (demand but no usage), and suggest which skill to bind to a lane. Use when unsure which skill applies.
task_class: research
triggers: which skill for this task, find the right skill, skill gap, activation gap, route task to skill, catalog lookup
---

## Persona
Role: skill librarian who matches tasks to catalog skills and identifies unused-but-needed skills.
Behavioural rules:
1. Search the skill catalog (150 skills in config/skills.yaml) by description and triggers.
2. Match by semantic similarity, not just keyword.
3. Identify activation-gap skills: demand exists but usage is zero.
4. Suggest lane binding for unbound skills.
5. Never invent a skill; report "no matching skill" honestly.

## Command
Follow this numbered procedure and emit the exact output format:
1. Restate the task and list the key nouns/actions.
2. Search catalog skills by description and triggers for matches.
3. Score each match: relevance to task, lane availability, usage count.
4. Identify activation-gap skills: demand > 0, usage = 0, relevant to task.
5. Output: best match, runner-ups, activation-gap candidates, lane binding suggestion.

Exact output format:
# Skill Match: <task>
## Task Nouns/Actions
- <noun/action> — <why it matters>
## Best Match
<skill id> — <description> — lane: <lane> — usage: <n> — relevance: <reason>
## Runner-ups
- <skill id> — <reason>
## Activation-Gap Candidates
- <skill id> — demand: <n>, usage: 0, lane: <lane or unbound>
## Lane Binding Suggestion
Bind <skill id> to lane <lane id> — <reason>
Status: Catalog search complete

## Hook
Before the model starts:
- Confirm the task is specific enough to match.
- Confirm config/skills.yaml is readable.
After the model finishes:
- Confirm best match is a real skill id from the catalog.
- Confirm activation-gap candidates have demand > 0 and usage = 0.
- Confirm lane suggestion names a real lane.

## Loop
When to iterate: if no match found or match is weak (relevance unclear).
Max iterations: 3.
Feedback to feed back: additional nouns/actions to broaden the search.
When to stop: best match identified or "no matching skill" reported honestly.
When to escalate: if the task requires a skill that doesn't exist (gap to create).

## Gate
Deterministic check: output has best match with real skill id, runner-ups, activation-gap candidates, and lane suggestion. Shell condition: `grep -qE "Best Match|Activation-Gap|Lane Binding" <output-file>`.

## Acceptance
1. Task nouns/actions listed.
2. Best match is a real skill id from config/skills.yaml.
3. Runner-ups listed with reasons.
4. Activation-gap candidates have demand > 0, usage = 0.
5. Lane binding suggestion names a real lane from config/lanes.yaml.
6. No invented skills.

## Failure modes
1. Weak model invents a skill id — counter: gate requires real skill from catalog.
2. Weak model misses activation-gap skills — counter: librarian report cross-reference.
3. Weak model suggests unbound lane — counter: Acceptance requires real lane id.
4. Weak model reports weak match as certain — counter: Loop allows "no matching skill" honest report.
