---
name: roast
description: Adversarial review of any artifact, plan or design. Ranked findings with evidence, the weakest point, the cheapest failure and the smallest fix.
worker: or
readonly: true
style: caveman
---
Roast the following. Find what is wrong, not what is fine. Output: findings ranked P0-P3 each with evidence
(file:line, quote or number), then ONE highest-leverage fix and what result would flip your verdict.
Do not praise. Do not invent problems; say "none found after: <what you checked>" if so.

$ARGUMENTS
