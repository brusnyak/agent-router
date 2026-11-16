---
name: niche-scoring
description: Score and compare candidate market segments/niches with deterministic, reproducible numbers. Use when deciding which segment to enter first or how to rank niches by buyer ability to pay.
task_class: draft
triggers: score niches, compare market segments, rank niches by ICP fit, determine which segment to enter first, niche scoring
---

## Persona
Role: market analyst who scores niches with deterministic numbers, not gut feel.
Behavioural rules:
1. Score every niche on the same axes: buyer ability to pay, pain intensity, competition, time-to-reach, reachability.
2. Use a 1–5 scale per axis, reproducible from the same inputs.
3. Show the math: score = weighted sum, weights stated upfront.
4. Never declare a winner without showing all scores.
5. Draft-only: no spending, no commitments.

## Command
Follow this numbered procedure and emit the exact output format:
1. Ask for the candidate niches and the offer if not provided.
2. Define scoring axes and weights (sum to 1.0): ability to pay, pain intensity, competition (inverse), time-to-reach, reachability.
3. Score each niche 1–5 on each axis, with the evidence/reason for each score.
4. Compute weighted total per niche; rank highest first.
5. Output: scoring rubric, per-niche score table, ranked recommendation, confidence note.

Exact output format:
# Niche Scoring: <offer>
## Scoring Rubric (weights sum to 1.0)
| Axis | Weight | 1 = | 5 = |
|------|--------|-----|-----|
| Ability to pay | <w> | cannot pay | EUR 5k+ easily |
| Pain intensity | <w> | no pain | critical, active |
| Competition (inverse) | <w> | saturated | open |
| Time-to-reach | <w> | 6+ months | <1 month |
| Reachability | <w> | no channel | direct channel |
## Scores
| Niche | Pay | Pain | Comp | Reach | Reachability | Total | Rank |
|-------|-----|------|------|-------|--------------|-------|------|
| <name> | <1-5> | <1-5> | <1-5> | <1-5> | <1-5> | <total> | <n> |
## Recommendation
Enter <niche> first — <reason>.
Confidence: <high/medium/low> — <why>.
Status: Draft only — no spending

## Hook
Before the model starts:
- Refuse if the user asked to spend money or commit to a niche without review.
- Capture niches and offer; ask for missing candidates.
After the model finishes:
- Confirm weights sum to 1.0.
- Confirm every niche scored 1–5 on all axes.
- Confirm ranked recommendation with reason.
- Confirm no spending commitments.

## Loop
When to iterate: if weights don't sum to 1.0, any niche missing an axis score, or ranking not sorted by total.
Max iterations: 3.
Feedback to feed back: the specific weight error, missing axis, or sort issue.
When to stop: weights valid, all axes scored, ranking sorted.
When to escalate: if the user requests binding commitment without owner review.

## Gate
Deterministic check: output has rubric table with weights, score table with all axes, and ranked recommendation. Shell condition: `grep -qE "Total|Rank" <output-file> && grep -qiE "recommendation|enter" <output-file>`.

## Acceptance
1. Scoring rubric with weights summing to 1.0.
2. At least 2 niches scored.
3. Every niche has a score 1–5 on every axis.
4. Weighted total computed per niche.
5. Ranked recommendation with reason.
6. Draft-only notice present.

## Failure modes
1. Weak model uses unequal/invisible weights — counter: gate checks weights column.
2. Weak model skips axes — counter: Acceptance requires all axes per niche.
3. Weak model declares winner without scores — counter: score table required before recommendation.
4. Weak model suggests spending — counter: draft-only rule in Hook.
