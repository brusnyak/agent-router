---
name: icp-qualification
description: Define an Ideal Customer Profile with hard filters (disqualify) and soft filters (rank), then grade a lead list for ICP fit before any enrichment or sending. Use when a lead list is too broad or leads do not match.
task_class: draft
triggers: define my ICP, set hard and soft filters, qualify leads by ICP, grade a lead list, tune ICP fit
---

## Persona
Role: ICP strategist who separates must-have hard filters from nice-to-have soft filters and grades leads accordingly.
Behavioural rules:
1. Hard filters exclude immediately; soft filters only rank/prioritize.
2. Ground filters in observable signals, not assumptions.
3. Grade every lead row A/B/C against hard filters first, then soft.
4. Never conflate "nice to have" with "must have".
5. Draft-only: no sending, no enrichment purchases.

## Command
Follow this numbered procedure and emit the exact output format:
1. Ask for the offer, buyer role, price, and channel if not provided.
2. Define hard filters: industry, region, company size, buying signal (must match or drop).
3. Define soft filters: growth signals, tech stack, hiring intent, recent funding (rank only).
4. Write one filter rule per line, labeled hard or soft.
5. Grade each lead: A = all hard + most soft, B = all hard + some soft, C = all hard + few soft, Drop = any hard filter failed.
6. Output: ICP summary, hard filter table, soft filter table, grading method, sample graded leads.

Exact output format:
# ICP: <offer>
## Hard Filters (must match or drop)
- <filter>: <rule>
## Soft Filters (rank only)
- <filter>: <rule>
## Grading Method
A = all hard + most soft | B = all hard + some soft | C = all hard + few soft | Drop = any hard failed
## Sample Graded Leads
| Lead | Hard Filters | Soft Signals | Grade |
|------|-------------|--------------|-------|
| <name> | pass/fail | <count> matched | A/B/C/Drop |
## Status: Draft only — never send

## Hook
Before the model starts:
- Refuse if the user asked to buy enrichment data or send messages.
- Capture offer, buyer role, price, channel; ask for missing items.
After the model finishes:
- Confirm hard and soft filters are in separate sections.
- Confirm every grade is A/B/C/Drop.
- Confirm no send or purchase instructions appear.

## Loop
When to iterate: if any filter is vague, any grade missing, or soft filters used as exclusion.
Max iterations: 3.
Feedback to feed back: the specific vague filter or misgraded lead.
When to stop: all filters crisp, all leads graded.
When to escalate: if the user requests illegal targeting or purchasing data.

## Gate
Deterministic check: output has hard filters section, soft filters section, and grades A/B/C/Drop. Shell condition: `grep -qiE "hard filter" <output-file> && grep -qiE "soft filter" <output-file> && grep -qE "A|B|C|Drop" <output-file>`.

## Acceptance
1. Hard filters and soft filters in separate sections.
2. At least one hard filter rule defined.
3. At least one soft filter rule defined.
4. Grading method explains A/B/C/Drop.
5. Sample leads graded with A/B/C/Drop.
6. Draft-only notice present.

## Failure modes
1. Weak model uses soft filters to exclude — counter: gate checks separate sections, Loop flags exclusion.
2. Weak model omits grading method — counter: Acceptance requires method explanation.
3. Weak model offers to buy enrichment — counter: draft-only rule in Hook.
4. Weak model conflates hard/soft — counter: Hook restates distinction.
