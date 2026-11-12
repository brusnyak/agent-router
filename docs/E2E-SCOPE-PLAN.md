# Agent Router: E2E scope plan (2026-11-12, Plan agent + checks)

Product: raw request -> engineered prompt (library: skills/personas/commands/clips) -> cheapest capable executor -> verified result -> cleanup -> remembered state. One API/MCP for any frontend.

## Pipeline state
| Stage | State | Gap |
|---|---|---|
| Intake (CLI/serve/MCP/jobs) | exists | |
| Understand goal (retrieval + decide) | partial | decide sees top 6 hits x 100 chars; eval only 24 queries |
| Assemble engineered prompt | partial, thinnest | only 1 body injected, 1500 chars (core.py:205-216); no composer (role/goal/constraints/acceptance/format) |
| Choose executor | partial | no task-class -> tier policy; config/lanes.yaml unwired |
| Execute local/Oracle | works | Oracle not re-synced, no git remote |
| Execute browser | missing | ego-browser present in capabilities.json, no worker |
| Verify | weak | `verified` = gate exit 0 or false; a review citing 5 fake files passed |
| Clean up | partial | no tab cleanup (no browser worker) |
| Remember/sync | partial | no step resume, no Mac<->Oracle state sync |

Usable agents (data/capabilities.json): claude, codex, kilo, pi. Not usable: qwen, gemini. opencode and cline are not probed.

## Tiers (proposed; `decide` emits `tier`)
classify/route/summarize -> NIM_1 chat | bounded code edit with gate -> pi on NIM_2/3 | short drafts -> @or | multi-file/real bugfix -> codex | review/judgment/plan -> claude sonnet | long unattended -> Oracle | web research -> browser worker (Mac).

## Sub-agents
Router is the only spawner, depth 1. max_parallel=3, max_expert=1, max_subtasks=4. Packet per subtask: engineered prompt + 1-3 sibling facts + owned files + gate. Deterministic patch merge; overlapping files rejected. No verifiable artifact => `unverified`, never "done".

## Milestones (each ends in a runnable demo; stop at first failing gate, write a ticket)
- M0 (S) docs consolidation + G1: rename `verified` -> `gate_passed`, add evidence check (cited paths must exist). Demo: fixture citing nope.py -> verified=false.
- M1 (M, owner-approved spend) kill test: 10 real tasks x 3 arms (raw->Claude, raw->NIM, router->NIM), blind rubric. Gate: router beats raw-NIM on >=7/10 and within 1 point of Claude, else cut composer scope and stop building breadth.
- M2 (M) prompt composer + tier policy; `ask --dry` prints engineered prompt + sources; re-run M1.
- M3 (S) fresh-HOME `init`; probe opencode/cline or drop them.
- M4 (M) Oracle sync (needs owner for git remote).
- M5 (M) parallel with state: caps, patch merge, blocked/pending table.
- M6 (M, owner logins) browser worker: read page, no leaked tab; Deep Research stays gated.
- M7 UI check (owner views 1440/390 screenshots) + Telegram/OpenClaw-Hermes adapters.
- M8 missing-capability tickets (retrieval top1 < threshold -> ticket, no auto-install); then fold ~/.agent-skills/router/router.py into `backbone library`.

## Spec consolidation
One doc `docs/AGENT_ROUTER.md`; README ~30 lines; keep DESIGN.md. Archive PRODUCT_SPEC, SPEC, SCOPE, PLAN-2026-11-12, PHASE1/2, PRODUCT, ROWS_ANALYSIS to docs/archive/. Check PORTABLE_DEPLOYMENT_SPEC, CROSS_DEVICE_SPEC, DEVELOPMENT_LOOP for unique content first.

## Adapter references on disk
~/Developer/ecc-reference/docs/HERMES-OPENCLAW-MIGRATION.md, ~/.agent-skills/vendor/msitarzewski_agency-agents/integrations/openclaw, ~/.agent-skills/adapters/{claude,codex,opencode}. ~/Developer/hermes-dashboard is a UI reference, not an adapter.

## Risks
1. Premise unproven (T9 24/24 vs 24/24; L3 A/B per HANDOFF: router 19 min vs Claude 4 min, fabricated output). 2. False "verified". 3. Scope sprawl: 13 specs, two skill routers.
