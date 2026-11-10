# langgraph-router

A lightweight, open-source multi-agent router with a LangGraph reasoning layer and Kanban UI. Connects to Orca, raw NIM keys, Claude, Codex, OpenCode, Cline, Kilo, and Hermes — without requiring OpenCode or Zed as intermediaries.

## What it does

- **Single concentrated chat input** — dump your thoughts in plain language
- **LangGraph supervisor (NIM 3)** — classifies intent, picks the right agent + skill + MCP, dispatches work
- **Kanban board** — Backlog / Triaging / Running / Review / Done / Blocked with delegation flow, token tracking, analytics
- **Self-configurable** — agents, skills, lanes, models, projects all driven by YAML config files (not hardcoded)
- **Human-in-the-loop** — `interrupt()` before send/spend/deploy/push/delete/auth
- **Project selection** — auto-discovers projects with `AGENTS.md`, loads project context into the supervisor

## Architecture

```
You type thought → Web UI (React + Tailwind) → FastAPI → LangGraph Supervisor (NIM 3)
                                             ↓
                                    Reads agents.yaml / skills.yaml / lanes.yaml / projects.yaml
                                    Picks agent + model + prompt → dispatches
                                    Writes card to SQLite Kanban → streams result
                                    You reply → re-route
```

## Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, LangGraph (`create_supervisor`), SQLite |
| Supervisor model | NIM 3 (`nemotron-3.5-super-vl-120b-a12b`) |
| Frontend | React + Vite + Tailwind CSS (OpenCode-style layout) |
| Agent dispatch | `orca agent launch`, `codex exec`, `nim_call.py` (direct NIM, bypasses OpenCode/Zed) |
| Config | YAML: agents, skills, lanes, models, projects, MCP |

## Config files (`config/`)

- `config.yaml` — host, port, db path, supervisor model, project roots
- `agents.yaml` — auto-detected CLIs (claude, codex, opencode, nim3, nim2, nim1, kilo, cline, hermes)
- `skills.yaml` — scanned from `~/.claude/skills/` and `~/.agent-skills/`
- `lanes.yaml` — dispatch lanes (build, review-roast, ops-repair, research-public, etc.)
- `models.yaml` — model endpoints + API key env names
- `projects.yaml` — discovered projects with `AGENTS.md` context
- `mcp.yaml` — MCP server definitions

## Quick start

```bash
# Backend
cd ~/Developer/agent-router
pip install -r requirements.txt
python main.py          # serves on http://127.0.0.1:8080

# Frontend (new terminal)
cd ui
npm install
npm run dev             # serves on http://localhost:5173
```

## MVP status

Scaffold complete. Backend runs, DB initializes, API endpoints exposed. Next: end-to-end test of one chat → LangGraph → agent dispatch → Kanban card.

## License

MIT
