# langgraph-router

A lightweight, open-source multi-agent router with a LangGraph reasoning layer and Kanban UI. Connects to Orca, raw NIM keys, Claude, Codex, OpenCode, Cline, Kilo, and Hermes — without requiring OpenCode or Zed as intermediaries. Config-driven: agents, skills, lanes, models, and projects are discovered from YAML + environment, not hardcoded.

## What it does

- **Single concentrated chat input** — dump your thoughts in plain language
- **LangGraph supervisor (NIM 3)** — LLM-based reasoning layer that classifies intent, picks the right agent + skill + MCP + prompt, dispatches work
- **Machine discovery** — auto-scans PATH, config dirs, API keys, browsers, vault, skills, hooks, and project roots on first run
- **Self-configuration** — generates models.yaml, agents.yaml, skills.yaml, lanes.yaml from discovered inventory (never installs anything)
- **Local index** — SQLite FTS5 + TF-IDF index over 9,000+ docs (skills, hooks, vault, repos, last30days) for index-aware routing
- **Kanban board** — Backlog / Triaging / Running / Review / Done / Blocked with delegation flow, token tracking, analytics
- **Prompt library** — loads SKILL.md files from ~/.claude/skills/ and ~/.agent-skills/, injects them into agent system prompts
- **Agent abstraction** — CLI agents (claude, codex, opencode, etc.) and NIM agents (direct NIM API calls, bypassing OpenCode/Zed)
- **Human-in-the-loop** — `interrupt()` before send/spend/deploy/push/delete/auth/vault-write
- **Config drift** — PEEM evaluation feedback → routing constraints + proposals (suggest + gate, never auto-applied)
- **Proactive loop** — research sub-agent → review critic (loop interception at 3×) → interrupt gate → execution
- **Browser automation** — system-controlled Neo/Ego browser for Gemini deep research (chat-based interaction)
- **Evaluation** — NIM 3 as LLM judge scoring PEEM criteria on completed cards
- **Project selection** — auto-discovers projects with AGENTS.md, loads project context into supervisor
- **Token analytics** — per-agent/model/lane token usage with optimization suggestions

## Architecture

```
You type thought → Web UI (React + Tailwind, Orca-style dark IDE) → FastAPI → LangGraph Supervisor
                                              ↓
                                     Machine Discovery (first run)
                                              ↓
                                     Self-Configuration (YAML from inventory)
                                              ↓
                                     Local Index (skills, hooks, vault, repos)
                                              ↓
                                     Index-Aware Triage (right model for right task)
                                              ↓
                                     Drift Constraints (from PEEM feedback)
                                              ↓
                                     Human-in-the-Loop Gate (interrupt on gate words)
                                              ↓
                                     Dispatch (shell=False, worktree isolation)
                                              ↓
                                     Agent (CLI or NIM direct API)
                                              ↓
                                     Kanban Card + PEEM Evaluation
                                              ↓
                                     Config Drift Proposals (review before apply)
```

## Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, LangGraph (`StateGraph`), SQLite |
| Supervisor model | NIM 3 (`nemotron-3.5-super-vl-120b-a12b`) via `nim_call.py` |
| Frontend | React + Vite + Tailwind CSS (Orca-inspired dark IDE) |
| Agent dispatch | `shell=False` subprocess, git worktree isolation, PTY wrapper for interactive CLIs |
| Config | YAML: agents, skills, lanes, models, projects, MCP (auto-generated from discovery) |
| Index | SQLite FTS5 + TF-IDF cosine similarity (stdlib only) |
| Evaluation | NIM 3 LLM judge, PEEM criteria, stored in SQLite |
| Config drift | Suggest + gate (owner applies via interrupt) |

## Config files (`config/`)

- `config.yaml` — host, port, db path, supervisor model, project roots
- `agents.yaml` — agents with CLI, model, provider, write access, route reasons, skills (auto-generated)
- `skills.yaml` — skills loaded from SKILL.md files (auto-generated)
- `lanes.yaml` — dispatch lanes with acceptance checks, forbidden actions, skills (auto-generated)
- `models.yaml` — model endpoints + API key env names (auto-generated)
- `projects.yaml` — projects with AGENTS.md/CLAUDE.md context, preferred lanes
- `mcp.yaml` — MCP server definitions
- `discovered-inventory.json` — machine discovery output (generated, gitignored)
- `index.db` — local search index (generated, gitignored)
- `drift/config-drift.yaml` — PEEM-driven routing proposals (generated, gitignored)

## Quick start

```bash
# Setup (one-time)
cd ~/Developer/agent-router
make setup

# Set API keys (from ~/.env)
export NIM_3=<your-nim-3-key>
export NIM_2=<your-nim-2-key>
export NIM_1=<your-nim-1-key>
export ANTHROPIC_API_KEY=<your-key>
export OPENAI_API_KEY=<your-key>
export GEMINI_API_KEY=<your-key>

# Run machine discovery (first run)
python scripts/discover_machine.py

# Self-configure from discovered inventory
python scripts/configure_from_discovery.py

# Build local index
python scripts/index_vault.py

# Start everything (backend + frontend)
make start

# Backend: http://127.0.0.1:8080
# Frontend: http://localhost:5173
```

## Docker

```bash
docker build -t agent-router .
docker run -p 8080:8080 --env-file ~/.env agent-router
```

## Makefile targets

| Target | Description |
|---|---|
| `make setup` | Full setup: Python venv + npm install |
| `make start` | Start backend (8080) + frontend (5173) |
| `make stop` | Stop all processes |
| `make restart` | Restart everything |
| `make test` | Backend smoke test + pytest |
| `make db-init` | Initialize SQLite database |
| `make lint` | Lint Python code |
| `make format` | Format Python code |
| `make clean` | Remove venv, node_modules, db |

## Test suite

```bash
# Run all tests (stdlib only, no external installs)
python tests/test_discovery.py
python tests/test_indexer.py
python tests/test_drift.py
python tests/test_agent_base.py
python tests/test_supervisor.py

# Or via pytest if installed
python -m pytest tests/ -v
```

## Design

UI follows the [impeccable](https://github.com/opencode/skills/impeccable) craft floor: obsidian dark theme, Geist font, restrained color strategy (neutrals + electric-blue accent), no gradients/glass/neon, Orca-inspired layout (left nav + main chat + analytics sidebar + status bar). See `DESIGN.md` for the full token specification.

## Evaluation

POST `/api/evaluate/all` — runs NIM 3 as LLM judge over all completed cards, scoring PEEM criteria. Results stored in SQLite, exposed via `/api/evaluate/analytics`.

## Config Drift

After evaluations accumulate, `scripts/config_drift.py` analyzes PEEM scores and proposes routing constraints (avoid consistently failing agents/models), model routing guidance, and prompt/lane updates. All proposals are `status: proposed` — the owner reviews and applies via interrupt gate. Nothing is auto-applied.

## License

MIT

## Shadow hook, librarian, compiler (2026-11-13)

Shadow-first context hook for Claude Code. It logs what it would suggest and injects nothing.

- `backbone/hook.py`: UserPromptSubmit hook, LLM-free, network-free, fails open. Receipts hold a hash and length, never prompt text. `backbone/hook_log.py` joins outcomes and reports treat vs holdout (`python3 -m backbone.hook_log report`).
- `scripts/shadow_hook.py status|install|uninstall`: edits `~/.claude/settings.json` (backup first, removes only its own entries). `scripts/outcome_hook.py` logs Skill/Agent/Task outcomes.
- `backbone/compile.py`: turns a dictation into a short fact card (entities copied verbatim; falls back to rules without an LLM).
- `eval/librarian.py`: propose-only catalog report (usage, duplicates, staleness); never moves files. `scripts/nightly.sh` chains catalog, enrich, librarian, report (`NIGHTLY_DRY=1` prints only).
- Measured (silver labels are LLM-made, unverified): 517 of 1,011 prompts labelled; dense retrieval top-1 25% / top-3 46% vs 14% guess floor. Not an auto-picker.
- Invariants and tests: `docs/INVARIANTS.md`. Status and next steps: `HANDOFF.md`. Oracle/Hermes: `docs/ORACLE-HERMES.md`.
