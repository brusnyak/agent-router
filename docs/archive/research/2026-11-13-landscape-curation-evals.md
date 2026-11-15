# Landscape: skill curation + eval/memory (2026-11-13)

Method: ego-browser (space 5, tab p1 only, read-only). Stars, last commit, license read from GitHub repo pages on 2026-11-13. Quote = repo page title/description text. "unverified" = not pulled this session.

## Sub-task 1: skill/agent catalog lifecycle

| # | Candidate | URL | Stars | Last commit | License | Quote (page text) | What it does / fit | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | cc-skill-usage (FlorianBruniaux) | https://github.com/FlorianBruniaux/cc-skill-usage | 9 | 2026-09-28 | MIT | "Retroactive Claude Code Skill usage analytics. Single-file Python CLI, reads your existing ~/.claude transcripts, counts real Skill tool_use invocations (not prose mentions). No hook to install ahead of time." | Usage counts from transcripts, Python, local. Direct fit for usage score. | USE |
| 2 | skills-mgr (Jackeyzhe) | https://github.com/Jackeyzhe/skills-mgr | 2 | 2026-06-07 | MIT | "CLI tool for managing AI agent skills: usage analysis, duplicate detection, safe removal with backup, dependency health checks, and cross-tool symlink sync" | Covers duplicates + backup-before-removal. Small, young. | STEAL-IDEA (backup-before-remove, duplicate check) |
| 3 | recca0120/skills-refactor | https://github.com/recca0120/skills-refactor | 1 | 2026-01-19 | MIT | "Claude Code Skills for analyzing, refactoring, and validating skills - Lint checks, duplicate detection, and shared module extraction" | Lint + duplicate detection. Stale since Jan. | STEAL-IDEA |
| 4 | agnix (agent-sh) | https://github.com/agent-sh/agnix | 482 | 2026-11-13 | MIT | "The missing linter and lsp for AI coding assistants. Validate CLAUDE.md, AGENTS.md, SKILL.md, hooks, MCP. Plugin for all major IDEs included, with autofixes." | Lint gate for SKILL.md and CLAUDE.md. Most mature linter found. | USE (lint gate, read-only mode) |
| 5 | claudelint (pdugan20) | https://github.com/pdugan20/claudelint | 15 | 2026-11-13 | MIT | "A linter for Claude Code projects. Validates CLAUDE.md files, skills, settings, hooks, MCP servers, and plugins." | Broad linter, low adoption. | STEAL-IDEA |
| 6 | cclint (dotcommander) | https://github.com/dotcommander/cclint | 18 | 2026-11-04 | MIT | "Linter for Claude Code agents, commands, and skills" | Narrow linter. | STEAL-IDEA |
| 7 | SkillCheck-Free (olgasafonova) | https://github.com/olgasafonova/SkillCheck-Free | 42 | 2026-10-11 | MIT | "Validate Claude Code skills against the agentskills specification (Free tier)" | Spec validator. Points at the spec below. | STEAL-IDEA (validate vs spec) |
| 8 | agentskills spec (agentskills) | https://github.com/agentskills/agentskills | 27.3k | 2026-11-04 | Apache-2.0 | quote unverified (about text not pulled) | Upstream spec for SKILL.md format. Use as the validation reference, not a tool. | USE (spec reference) |
| 9 | skill-analytics (Suketu-Patel) | https://github.com/Suketu-Patel/skill-analytics | 0 | 2026-05-18 | MIT | "Local Next.js dashboard for analyzing Claude Code + Codex usage with LLM-as-judge." | Heavy UI, LLM-as-judge costs money. | SKIP |
| 10 | claude-skill-analytics (Salmonellasarduri) | https://github.com/Salmonellasarduri/claude-skill-analytics | 2 | 2026-07-14 | MIT | "Claude Code plugin for automatic skill usage tracking and analytics" | Hook-based tracking (forward-looking, not retro). | STEAL-IDEA (hook logging) |
| 11 | skillusage (lovstudio) | https://github.com/lovstudio/skillusage | 3 | 2026-06-11 | MIT | "Skill / slash-command usage analytics for Claude Code and Codex, from local on-disk data" | Local on-disk, covers Codex too. | STEAL-IDEA |
| 12 | anthropics/skills | https://github.com/anthropics/skills | 194k | 2026-11-06 | not shown in page header (unverified) | quote unverified | Official skill examples. skill-creator SKILL.md last changed 2026-03-06. Upstream for official skills. | USE (upstream source for update check) |
| 13 | vercel-labs/skills | https://github.com/vercel-labs/skills | 39.2k | 2026-11-12 | MIT | quote unverified | Installer CLI for agent skills. Need to check whether it exposes an update command. | unverified (check before USE) |
| 14 | ccusage (ryoppippi, now ccusage/ccusage) | https://github.com/ccusage/ccusage | 19.4k | 2026-11-13 | MIT | quote unverified | Token/cost usage from Claude JSONL. Not skill-level. | STEAL-IDEA (JSONL parsing only) |
| 15 | obra/superpowers | https://github.com/obra/superpowers | 317k | 2026-11-03 | MIT | quote unverified | Large skill pack distributed as plugin. Example of plugin versioning, not a tool. | SKIP as tool |
| - | Chainguard-dev/agent-skill-lint | https://github.com/Chainguard-dev/agent-skill-lint | - | - | - | none | Page not found under that name. Dropped. | unverified / not found |

### Upstream update mechanism (Claude Code docs, read 2026-11-13)
- URL: https://code.claude.com/docs/en/plugins/host-marketplace
- Quote: "a user gets a new copy of a plugin only when its computed version changes"
- Quote: "Background auto-update ... It's off for your marketplace until a user or admin turns it on"
- Quote: "When users add your marketplace from a shared directory, Claude Code reads plugins with relative-path sources directly from that directory instead of copying them."
- Meaning: a git/plugin install only gets updates when version changes. Upstream check = compare installed version or commit with remote. Local (symlinked) skills update instantly.
- Version field detail (plugin.json vs commit SHA): unverified this session.

### Recommended librarian design (propose only)
- Inputs: ~/.claude/skills, plugin cache, ~/.claude transcripts (Skill tool_use), vault pages, optional git remote per installed skill.
- Scoring: usage (cc-skill-usage style count, 30/90 day), demand (owner requests and router hint hits), duplicates (name + description similarity, skills-mgr style), staleness (last edit or upstream commit age), upstream (git ls-remote or plugin version diff vs installed).
- Outputs: KEEP / MERGE / UPDATE / RETIRE / ACQUIRE. Each row with the evidence fields behind it.
- Lint gate: agnix or SkillCheck-style spec check before KEEP.
- Safety: nothing deleted without owner approval. RETIRE = move to a dated archive dir with a manifest (path, hash, reason) so restore is one command. ACQUIRE = propose only, no install.

## Sub-task 2: evaluation and context memory

Offline-on-Mac and NIM columns are NOT verified this session (only repo pages read). Marked unverified.

| # | Candidate | URL | Stars | Last commit | License | Quote (page title text) | What it does | Mac/Python/NIM offline | Maturity | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | promptfoo | https://github.com/promptfoo/promptfoo | 27.1k | 2026-11-13 | MIT | "Test your prompts, agents, and RAGs ... Simple declarative configs with command line and CI/CD integration" | YAML prompt/route tests, CI | NIM: unverified (OpenAI-compatible provider expected) | high | USE for offline replay of routing cases |
| 2 | Inspect AI | https://github.com/UKGovernmentBEIS/inspect_ai | 3.2k | 2026-11-13 | MIT | "Inspect: A framework for large language model evaluations" | Python eval framework, solvers + scorers | Python: yes per docs (unverified here) | medium-high | STEAL-IDEA (scorer pattern), SKIP as dependency |
| 3 | Langfuse | https://github.com/langfuse/langfuse | 37.4k | 2026-11-13 | MIT | "Open source AI engineering platform: AI Gateway, agent observability, evals, and prompt/skill management, built on OpenTelemetry" | Tracing + evals platform | Self-host needs Docker/Postgres: heavy, unverified | high | SKIP for now (overkill; log to JSONL) |
| 4 | Phoenix (Arize) | https://github.com/Arize-ai/phoenix | 12.3k | 2026-11-13 | not shown in header (unverified) | "AI Observability & Evaluation" | Local trace UI + evals | pip-local expected: unverified | high | STEAL-IDEA (trace view later) |
| 5 | DeepEval (Confident AI) | https://github.com/confident-ai/deepeval | 19.5k | 2026-11-12 | Apache-2.0 | "The LLM Evaluation Framework" | pytest-style LLM metrics; LLM-judge metrics cost calls | judge metrics need an LLM: NIM possible, unverified | high | STEAL-IDEA (pytest pattern) |
| 6 | mem0 | https://github.com/mem0ai/mem0 | 68.9k | 2026-11-06 | Apache-2.0 | "The Memory Layer for AI Agents - Drop-in memory infrastructure for AI agents and apps" | Memory store with LLM extraction | needs LLM + embedder config; local possible, unverified | high | SKIP (adds extraction LLM calls to every write; vault already is memory) |
| 7 | Letta | https://github.com/letta-ai/letta | 25.4k | 2026-10-18 | Apache-2.0 | "Platform for stateful agents: AI with advanced memory that can learn and self-improve over time." | Stateful agent server | server process, heavy | high | SKIP (wrong shape) |
| 8 | Graphiti (Zep) | https://github.com/getzep/graphiti | 32.8k | 2026-11-11 | Apache-2.0 | "Build Real-Time Knowledge Graphs for AI Agents" | Temporal knowledge graph | needs graph DB + LLM: heavy | high | SKIP for v1; revisit if vault links matter |
| 9 | sqlite-vec | https://github.com/asg017/sqlite-vec | 8.3k | 2026-05-18 | MIT | "A vector search SQLite extension that runs anywhere!" | vector search in sqlite | yes by design (pure SQLite ext), unverified here | medium-high | USE (when vector needed) |
| 10 | LanceDB | https://github.com/lancedb/lancedb | 11.9k | 2026-11-13 | Apache-2.0 | "Developer-friendly OSS embedded retrieval library for multimodal AI. Search More; Manage Less." | embedded vector store | embedded, local: unverified here | high | STEAL-IDEA (keep as alt if sqlite-vec too small) |

Stdlib option (no candidate needed): SQLite FTS5, already in Python's sqlite3 build. Unverified on this Mac.

### Smallest stack for holdout A/B: "hint used" and "result accepted"
- Assign: hash(session_id) mod 10 == 0 is holdout (no hint shown). Log assignment before the hint is printed.
- Log one JSONL row per routing decision: session, arm, skill suggested, hint shown, and the skill the transcript shows as invoked (Skill tool_use).
- "Hint used" = suggested skill appears in transcript Skill tool_use within the same turn.
- "Result accepted" = no owner correction or revert in the next N turns (define N before the run), from transcript text.
- Analysis: Python stdlib sqlite3 table + two-proportion z-test. No new dependency.
- Offline replay of routing prompts: promptfoo YAML (one optional dep). Run before shadow mode, not as the live metric.
- Memory for vault context: FTS5 first; add sqlite-vec only if FTS5 misses cases in a measured set.

Pre-registration: fix arm split, N-turn window and the acceptance definition before the first row is logged.
