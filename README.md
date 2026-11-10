# langgraph-router

A lightweight, open-source multi-agent router with a LangGraph reasoning layer and Kanban UI. Connects to Orca, raw NIM keys, Claude, Codex, OpenCode, Cline, Kilo, and Hermes — without requiring OpenCode or Zed as intermediaries. Config-driven: agents, skills, lanes, models, and projects are discovered from YAML + environment, not hardcoded.

## What it does

- **Single concentrated chat input** — dump your thoughts in plain language
- **LangGraph supervisor (NIM 3)** — LLM-based reasoning layer that classifies intent, picks the right agent + skill + MCP + prompt, dispatches work
- **Kanban board** — Backlog / Triaging / Running / Review / Done / Blocked with delegation flow, token tracking, analytics
- **Prompt library** — loads SKILL.md files from ~/.claude/skills/ and ~/.agent-skills/, injects them into agent system prompts
- **Agent abstraction** — CLI agents (claude, codex, opencode, etc.) and NIM agents (direct NIM API calls, bypassing OpenCode/Zed)
- **Human-in-the-loop** — `interrupt()` before send/spend/deploy/push/delete/auth
- **Evaluation** — NIM 3 as LLM judge scoring PEEM criteria (accuracy, coherence, relevance, objectivity, clarity, conciseness) on completed cards
- **Project selection** — auto-discovers projects with AGENTS.md, loads project context into supervisor

## Architecture

```
You type thought → Web UI (React + Tailwind, Orca-style dark IDE) → FastAPI → LangGraph Supervisor (NIM 3)
                                             ↓
                                    Reads agents.yaml / skills.yaml / lanes.yaml / models.yaml / projects.yaml / mcp.yaml
                                    Auto-discovers agents via PATH + config file scan
                                    Builds dispatch packet from prompt library (SKILL.md + orchestration header)
                                    Dispatches to agent (CLI subprocess or direct NIM call)
                                    Writes card to SQLite Kanban → streams result back
                                    You reply → re-route
```

## Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, LangGraph (`StateGraph`), SQLite |
| Supervisor model | NIM 3 (`nemotron-3.5-super-vl-120b-a12b`) via `nim_call.py` |
| Frontend | React + Vite + Tailwind CSS (Orca-inspired dark IDE) |
| Agent dispatch | `orca agent launch`, `codex exec`, `nim_call.py` (direct NIM) |
| Config | YAML: agents, skills, lanes, models, projects, MCP |
| Evaluation | NIM 3 LLM judge, PEEM criteria, stored in SQLite |

## Config files (`config/`)

- `config.yaml` — host, port, db path, supervisor model, project roots
- `agents.yaml` — agents with CLI, model, provider, write access, route reasons, skills
- `skills.yaml` — skills loaded from SKILL.md files
- `lanes.yaml` — dispatch lanes with acceptance checks, forbidden actions, skills
- `models.yaml` — model endpoints + API key env names
- `projects.yaml` — projects with AGENTS.md/CLAUDE.md context, preferred lanes
- `mcp.yaml` — MCP server definitions

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

# Start everything (backend + frontend)
make start

# Backend: http://127.0.0.1:8080
# Frontend: http://localhost:5173
```

## Makefile targets

| Target | Description |
|---|---|
| `make setup` | Full setup: Python venv + npm install |
| `make start` | Start backend (8080) + frontend (5173) |
| `make stop` | Stop all processes |
| `make restart` | Restart everything |
| `make test` | Backend smoke test |
| `make db-init` | Initialize SQLite database |
| `make lint` | Lint Python code |
| `make format` | Format Python code |
| `make clean` | Remove venv, node_modules, db |

## Design

UI follows the [impeccable](https://github.com/opencode/skills/impeccable) craft floor: obsidian dark theme, Geist font, restrained color strategy (neutrals + electric-blue accent), no gradients/glass/neon, Orca-inspired layout (left nav + main chat + analytics sidebar + status bar). See `DESIGN.md` for the full token specification.

## Evaluation

POST `/api/evaluate/all` — runs NIM 3 as LLM judge over all completed cards, scoring PEEM criteria. Results stored in SQLite, exposed via `/api/evaluate/analytics`.

## License

MIT
