# Agent Router: vision (single source of intent)

Status: DRAFT v2, 2026-11-12. Owner: Yegor. This file says WHAT and WHY. How it is built: `AGENT_ROUTER.md` (spec), `COMPONENTS.md` (what to reuse), `RESEARCH-AND-REDESIGN.md` (evidence and faults found).

## 1. One sentence
Turn a lazy, raw request into the one great prompt (or two) that makes the best-suited agent deliver the whole result, then run it, verify it, and remember it.

## 2. The reference that defines success ("the Soul Knight test")
A friend asked for a web alternative of the classic Soul Knight (join fast, play with friends, the good old version). After a long discussion and confirmation with ChatGPT he produced a configured spec, and Codex built the game from TWO prompts. The value was not the model: it was the discussion, the research, the spec, the structure of the prompt.
The router is that discussion-and-prompt-engineering layer, done for me, because I will not write dedicated commands, styles and prompt structures by hand. My raw input only carries a note and a direction; the same input processed by a dedicated command, style and prompt is worth far more. The router closes that gap automatically.

Success = given a 3-sentence request, the router (1) asks only the questions that change the decision, (2) researches and gathers the components that already exist, (3) writes the spec and ONE master build prompt with acceptance gates, (4) hands it to the right executor, and (5) the result passes the gates in at most 2 prompts. Measured against the same request sent raw to the same executor. If it does not beat raw, the router is not worth it.

## 3. The pipeline (what it does for every request)
1 Intake: any channel (CLI, Telegram, web UI, API, MCP).
2 Understand: goal, task class, risk, what is missing. Deterministic retrieval first (library + memory), the model only when the scores are uncertain.
3 Clarify (only when the answer changes the decision): short questions, defaults proposed, answers remembered.
4 Gather: search the library, then owned material (vault, repos), then the web and GitHub for components that already exist; record licence and verdict (adopt / wrap / ideas only / skip).
5 Specify: spec + constraints + acceptance gates; for big work a MASTER BUILD PROMPT with sections fixed by `docs/AGENT_ROUTER.md`.
6 Compose: persona + command + skills + hook + loop + style + gate from the library, with provenance.
7 Route: choose the executor by a measured score (accuracy, cost, latency, quota), not a hand table: Claude (Sonnet/Haiku/Opus), Codex, three NIM keys, OpenRouter free, OpenCode/Cline/Kilo, a browser worker, a server node.
8 Execute: local, on the always-on server (Oracle) when the Mac is down, or in the browser; sub-agents only spawned by the router, depth 1, each with a packet (prompt, owned files, gate).
9 Verify: deterministic gates first (command, schema, cited-paths-exist), then a second look where it pays. Never report "verified" without evidence.
10 Clean up: worktrees, leases, browser tabs.
11 Remember: concrete session memory (pinned facts, folded summaries, decisions), outcome log that feeds routing and library quality.

## 4. Non-negotiables
- Standalone and open-source: no personal paths or ids in code; `init` discovers the machine; works on a fresh machine for any user.
- Reuse over rebuild: adopt existing components where they fit; own code is the glue, the curated library and the measured policy.
- Deterministic where possible, model where uncertain, and the model's choices are validated against what exists.
- Everything measured on held-out real prompts; no claim without the command that proves it.
- Outward actions (push, send, spend, delete) need an approval record; private notes go only to workers I am logged into myself.
- The Mac is the dev machine; Oracle is the always-on hub; Telegram and a UI are frontends; work continues when the Mac is down.

## 5. What the router adds that a raw prompt lacks
Best persona and command for the task; style; a gate that decides pass/fail; a retry loop with the right feedback; memory of earlier decisions; a verified component list instead of reinventing; a cheaper executor when the cheap one is enough, the strong one when it is not; a clean-up and a report.

## 6. Not the goal
Another IDE; a multi-user SaaS; routing other people's subscriptions; blind auto-installing of components; polishing features before the Soul Knight test passes.

## 7. Open points that still need a decision (discuss, then write into the spec)
1 Clarification protocol: how many questions maximum, which channel, how defaults are shown.
2 Master build prompt template: final section list (draft in `COMPONENTS.md`), size limits, where components and licences are listed.
3 What "good enough spec" means (a gate for the spec itself).
4 The first end-to-end target for the Soul Knight test (small web game? the router's own next feature?).
5 Component policy: dependency budget (stdlib+SQLite core, optional extras).
