# Agent Router: scope (2026-11-11, supersedes the scope sections of PRODUCT_SPEC.md)

## What it is
A personal, open-source **backbone** behind the agent surfaces already in use (Orca, Claude Code, Codex, OpenCode). One session in, the right worker out. It is not a new IDE and not a new gateway.

## Three layers (own only the middle one)
| Layer | Owner | Job |
|---|---|---|
| Gateway | **OmniRoute** (installed 3.8.51, loopback only) | 3 NVIDIA NIM keys (separate accounts, 40 RPM each) + OpenRouter free: rotation, fallback, usage |
| Brain | **this repo** | classify task, resolve skill/agent/prompt/hook, choose tier, plan, verify, escalate, log |
| Surface | Orca / Claude Code / small web chat | where the owner types and reads |

## Tiers
- **Worker** = NIM keys (and free models). Execute steps. Each key can host its own sub-agents.
- **Expert** = Claude, Codex (headless `claude -p`, `codex exec`). Plan once, review, resolve disputes. Escalation is by trigger, not by daily cap (owner 2026-11-11).
- Escalate when: deterministic check fails twice, task class is `plan|review|architecture`, judge models disagree.

## Index and resolver (reuse, do not rebuild)
`~/.agent-skills/router/router.py find` already indexes skills, agency agents, ECC, VoltAgent, Apple HIG and design-md (checked 2026-11-11: apple design, ecc reviewer, agency ui designer all return the right file). The gap is wiring and enforcement, not the index:
1. Brain must call it for every task and attach the top hits to the worker packet (supervisor.py:454 calls it; ROWS #12 says results are not used to pick lane/agent).
2. A hit above 0.35 that the worker ignores is a failed check.
3. No hit above 0.35 -> research step, then propose a new skill/config (owner approves).

## Goals and loops
A goal = objective + deterministic acceptance check + budget. Loop: expert plans -> workers execute -> check -> escalate on failure -> log trace. Loops improve by replaying the frozen task set, not by editing prompts blind.

## Target workloads (owner order)
1. Router develops itself (after the replay set is frozen).
2. BP and other repos in `~/Developer`.
3. Job pipeline (CV, applications): reuse `jobs_brief.py` gates; sends stay owner-approved.
4. Content/thought-dump engine: reuse before build; none found yet.

## Non-goals
Own key rotation/circuit breaker (OmniRoute), own IDE, multi-user SaaS, upstream PRs to OmniRoute, running claude/codex through OmniRoute OAuth (account risk).

## Proof ladder (each step has a command that passes or fails)
| # | Step | Check |
|---|---|---|
| 1 | Local branch `dev/backbone`, frequent commits, one squash push later | `git log`, remote unchanged |
| 2 | OmniRoute up on loopback, 3 NIM connections, combo `nim-pool` | 60-request burst spreads over 3 keys, no 429 surfaced |
| 3 | Orca/Claude Code base URL -> OmniRoute | one agent turn completes on a NIM model |
| 4 | Replay set, 12 real tasks x 3 arms (NIM alone / NIM+scaffold / Claude) | scored table; decides how much brain to build |
| 5 | Policy table + headless CLI dispatch (remove interactive_mode gate, agent_base.py:181) | one build task completes through codex exec |
| 6 | Wire index hits into lane/agent/packet | test: task "apple design review" selects HIG skill |
| 7 | Goal loop | one goal completes unattended with trace |
| 8 | Chat + ledger UI | 390 px and desktop screenshots, caller views them |
| 9 | Self-dev | diff accepted only if replay score does not drop |

## Hygiene rules
- Close what you open: ego-browser task spaces end with `task.finish({ keep: [] })`; processes you start you stop.
- `bp/` and `*.bak-*` are not part of this repo (gitignored).
- Existing PRODUCT_SPEC/ROWS_ANALYSIS stay as history; rows 2, 3, 5, 6, 14, 15 are gateway-owned or deferred.
