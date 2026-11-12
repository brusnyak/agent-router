# Agent Router: master spec (DRAFT v1, 2026-11-12, owner review pending)

Single source of truth. Everything else lives in docs/archive and docs/appendix. Measured state: HANDOFF.md. Scoping evidence: docs/E2E-SCOPE-PLAN.md. Reference designs studied (patterns only, no code dependency): docs/ADAPTER-RESEARCH.md.

## 1. Product
A standalone, open-source agent router. You type a raw request from any channel (CLI, Telegram, web UI, API). The router understands the goal from its own prompt library, engineers the final prompt (persona, command, skill, hook, loop, system prompt), picks the cheapest capable executor (Claude Sonnet/Haiku/Opus, Codex models, NVIDIA NIM keys, OpenRouter free, OpenCode free, Cline, Kilo, Pi), runs it locally, on a server, or through a browser, verifies the result against evidence, cleans up, and remembers. If something needed is missing (design system, agent, skill) it says so and fetches candidates. It works the same on a fresh machine for any user.

## 2. Hard principles
P1 Standalone: one install, no dependency on Hermes/OpenClaw/ECC at runtime. Patterns may be copied, code is ours, licenses recorded.
P2 Zero hand-config: `backbone init` discovers CLIs, keys, library sources, hosts and channels, and writes the config. No owner-specific path or id in code (grep gate in CI).
P3 Evidence over assertion: a result is `verified` only by gates (command exit, cited paths exist, schema ok). Otherwise `unverified` with a reason.
P4 Provenance: every engineered prompt records which library rows shaped it.
P5 Cheapest-first, escalate on failure, experts one at a time, spend caps per run and per day.
P6 No push, send, spend or delete outside the run's declared scope without an approval record.
P7 Router is the only spawner of sub-agents (depth 1).

## 3. Topology: hub and nodes (answers "chat from Telegram, execute on the Mac")
- Hub = the always-on host (Oracle, or any VPS or the Mac itself if alone). Owns the channel connections (one Telegram poller per bot), the job queue, the state DB.
- Node = any machine that does work (Mac, Oracle, laptop). A node connects OUTBOUND to the hub (long-poll over HTTPS or WS, bearer token), declares capabilities (`doctor`: which CLIs and logins work, browser available, repos), and claims jobs addressed to it (`@mac`, `@oracle`) or matching capability. No inbound port on the Mac, no tunnel.
- Telegram -> hub -> job queue -> Mac node claims it -> result flows back the same path. Mac offline: job waits with a TTL, or auto-reroutes to a node that can run it (policy `on_node_offline: wait|reroute|ask`). Mac back: node resumes its claimed jobs from checkpoints.
- Single-machine mode: hub and node are one process. This is the default for a new user.

## 4. Channels (discovered, not hand-set)
Channel interface: `receive() -> Message`, `send(chat, text, kind)`, `pair()`. Adapters: cli, http (`serve`), mcp, telegram first; others copy the plugin-adapter pattern (small class + manifest).
Pairing handshake (fixes the manual chat-id problem and the bot-as-chat-id 403): `init` asks for the bot token only, asks the user to send `/start` to the bot, captures the real chat id from `getUpdates`, stores it, verifies with a test send. Output style per channel (short, no paragraphs for chat; config `style: chat|report`).
Channel choice for notifications: user's last active channel, else a configured home channel; logged with the reason.

## 5. Library (the foundation)
Kinds: command, skill, agent (persona), subagent (spec for spawning), system (system prompts), hook, loop (iteration recipes), prompt (reusable engineered prompts), design (design systems), clip (transcripts/notes), playbook (business: lead-gen, copy, sales, ICP).
Row = id, kind, name, description, body, tags, source path, license, content hash, last-indexed, quality score (from evals), usage count.
Sources are auto-discovered by `init` (`~/.claude`, `~/.agent-skills`, `~/.codex`, `~/.config/opencode`, known vendor repos under `~/Developer/refs`) plus user-added paths. Ingest is idempotent (hash), dedupes near-duplicates, flags missing front-matter.
Index: FTS5 + embeddings (NIM, fallback local) with RRF fusion; goal-classification step before retrieval (task class, domain, artifact type) so retrieval filters by kind first.
Current state (data/backbone.db): agent 293, skill 418, command 13, clip 2; NOT yet indexed: hooks, loops, system prompts, subagents (ecc-reference/agents, refs/VoltAgent), design systems (refs/awesome-design-md), ECC commands, business playbooks, vault pages with proven applications.

## 6. Pipeline
1 Intake (normalize, dedupe, attach session context).
2 Understand: classify task class + goal + risk; hybrid retrieval; deterministic validation (names must exist).
3 Compose: engineered prompt = system + persona + goal + constraints + inputs + acceptance + output format + selected skill excerpts; `ask --dry` prints it with provenance. Raw-passthrough fallback when retrieval confidence is below threshold (shown to the user).
4 Plan executor: tier policy table (task class -> tier -> concrete worker), spend cap, parallelism caps (3 NIM, 1 expert).
5 Execute: local, node, or browser worker (Ego CLI or Neo MCP); sub-agent packets (prompt + owned files + sibling facts + gate); patch merge rejects overlap.
6 Verify: gates (command), evidence check (every cited path/symbol exists), schema check, optional blind critic on a different model family. Field `gate_passed`, `verified` only when evidence checks pass.
7 Clean up: worktrees, leases, browser tab groups, temp files; logged.
8 Remember: run state, tickets, session summary, library usage and outcome feedback (feeds quality score).
Missing-capability: retrieval top1 below threshold or no persona for the task -> ticket `missing: X, candidates: ...` and optional fetch (GitHub/refs) behind an approval.

## 7. Executors and tiers (config table, probed by `doctor`)
classify/route/summarize -> NIM chat | bounded code edit + gate -> pi on NIM | short drafts -> OpenRouter free | multi-file/real bugfix -> Codex | review/judgment/plan -> Claude Sonnet (Opus on request) | cheap checks -> Haiku | long unattended -> server node | web/Deep Research -> browser worker on a node with the login. Executors failing `doctor` are dropped automatically; opencode and cline get probes or are removed from the claims.

## 8. Security and open-source readiness
Secrets only via env/keychain, never in DB, logs or prompts; redaction on output. Model-supplied gates/cwd limited to named gates and registered roots. Remote access: bearer token, loopback or TLS. License audit of every vendored library source recorded per row. Fresh-HOME test in CI. README quickstart under 5 minutes.

## 9. Milestones (each ends in a runnable demo; gate failure stops the run and writes a ticket)
M0 Spec merged + `verified` -> `gate_passed` + evidence check. Demo: fixture citing a missing file fails.
M1 Library foundation: new kinds, discovery, license + quality fields, idempotent ingest. Demo: `library stats` shows all kinds; retrieval eval >= 60 queries incl. hooks/loops/system/business; top3 >= 0.9.
M2 Composer + tier policy + raw-passthrough threshold. Demo: `ask --dry` prints sections + sources + tier.
M3 Kill test: the owner's real tasks x 3 arms (raw->Claude, raw->NIM, router->NIM), blind rubric + evidence check. Gate: router beats raw-NIM on >= 7/10 and is within 1 point of Claude, else reduce scope.
M4 Hub/node + Telegram pairing. Demo: message from Telegram runs on the Mac node with no inbound port; Mac offline -> waits or reroutes by policy.
M5 Parallel with state: caps, patch merge, blocked/pending table.
M6 Browser worker with cleanup. Demo: read a page, no leaked tab.
M7 UI (design tokens verified by screenshots) + extra channel adapters.
M8 Fresh-HOME init + open-source cut (grep gate for personal paths, license audit, quickstart).

## 10. Non-goals
Own IDE; multi-user SaaS; routing others' subscriptions; auto-installing missing assets without approval.

## 11. Open questions (owner)
Q1 "night closer": which project and goal is meant? Q2 Kaggle: may the router/agents use the owner's account, with a kernel cap? Q3 Hub default: Oracle always-on, or Mac when present? Q4 Telegram per-channel output style default: short chat. Q5 Sources to ingest in M1: confirm list in section 5 plus the vault's proven job applications (read-only).
