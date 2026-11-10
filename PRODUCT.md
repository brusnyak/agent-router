# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

delegated: Python FastAPI backend + React/Vite frontend + Tailwind CSS, local-only deployment on macOS

## Users

Yegor Brusnyak — a single power user who manages multiple AI agents (Claude, Codex, OpenCode, NIM 1/2/3, Hermes, Cline, Kilo) across multiple projects and needs one concentrated interface to dump thoughts, triage work, delegate to the right agent, and review results on a Kanban board.

## Product Purpose

A lightweight multi-agent router with LangGraph reasoning layer: the user types free-form thoughts into a single chat, an LLM supervisor (NIM 3) classifies intent, selects the right agent + skill + MCP + prompt, dispatches work, writes results to a Kanban board, and streams output back. The user can reply to re-route. No selling — personal command center.

## Positioning

Unlike Orca (which provides agent terminals but no self-routing LLM supervisor or Kanban visibility) and unlike generic agent boards (which hardcode agents), this is config-driven: agents, skills, lanes, models, and projects are all discovered from the environment and YAML files, not hardcoded. It connects to raw NIM keys directly without requiring OpenCode or Zed as intermediaries.

## Operating Context

- Runs locally on macOS (Oracle VM adds latency with no benefit for API models)
- Reads API keys from `~/.env` via `with-env` (NIM_1, NIM_2, NIM_3, ANTHROPIC_API_KEY, OPENAI_API_KEY)
- Discovers agents by scanning PATH + config files (~/.claude/, ~/.codex/, ~/.config/opencode/, ~/.orca/, ~/.hermes/)
- Discovers skills from ~/.claude/skills/ and ~/.agent-skills/
- Discovers projects by scanning for AGENTS.md in known roots
- Kanban + analytics stored in SQLite (`kanban.db`)
- Evaluation layer: NIM 3 as LLM judge scoring PEEM criteria on completed cards

## Capabilities and Constraints

Confirmed functionality:
- Single concentrated chat input → LangGraph supervisor → agent dispatch → Kanban card
- Human-in-the-loop via `interrupt()` before send/spend/deploy/push/delete/auth
- Kanban board: Backlog / Triaging / Running / Review / Done / Blocked
- Card detail: agent used, model, tokens spent, prompt sent, output, reply thread, delegation flow
- Analytics sidebar: agent usage, token costs, success/failure rate, PEEM evaluation scores
- Project selection with AGENTS.md context loading
- Self-detectable configuration (agents.yaml, skills.yaml, lanes.yaml, models.yaml, projects.yaml, mcp.yaml)

Technical constraints:
- API models use ~0 local RAM; no local Ollama/vLLM (swap risk avoided)
- Load cap: 4 workers / load < 6
- No sends/spends/deploys without owner approval (gate words trigger interrupt)
- MVP only: single chat → one agent → one card; multi-hop workflows are Phase 2

## Brand Commitments

None explicit. Dark, IDE-like aesthetic (Orca-inspired), Geist font, obsidian palette, high information density, no neon/gradients.

## Evidence on Hand

- Existing router at ~/.agent-skills/router/router.py (deterministic, not LLM-based — rejected as insufficient)
- Existing dispatch lanes at ~/memory-vault/pages/dispatch-routes.json (14 lanes)
- Existing intake hook at ~/.claude/hooks/intake_hook.py
- Existing enforcement hook at ~/.claude/hooks/agent-log.py
- Orca 1.4.248 running locally with agent terminals + hook interception
- Hermes Agent v0.22.2+canary on Oracle VM (unreliable — separate concern)

## Product Principles

1. Config-driven, not hardcoded — every agent, skill, lane, model, project is discoverable from YAML + environment
2. LLM reasoning layer — NIM 3 supervisor decides routing, not keyword matching
3. Agent-first UI — concentrated chat + Kanban, not generic admin dashboard
4. Human-in-the-loop — gate words require explicit approval before any external action
5. Observable — every dispatch shows agent, model, tokens, prompt, output, delegation flow
6. Lightweight — single command (`make start`) runs backend + frontend

## Accessibility & Inclusion

Dark mode primary, keyboard-navigable, visible focus states, reduced motion respected, contrast ≥4.5:1 for body text.

## Product Principles

1. Config-driven, not hardcoded
2. LLM reasoning layer (NIM 3 supervisor)
3. Agent-first UI (chat + Kanban)
4. Human-in-the-loop on gate words
5. Observable delegation flow
6. Lightweight single-command startup
