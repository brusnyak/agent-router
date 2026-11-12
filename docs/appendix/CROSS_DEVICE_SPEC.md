# Cross-Device Architecture — Agent Router

## Decision: Do NOT copy from cccc

cccc has Web UI + terminal + CLI + MCP + IM bridges, but it's a different architecture (Rust daemon, local-first Groups, IM bridges). Integrating it would be more work than building our focused bridge. We borrow **patterns** (worktree isolation, shell=False, proof bundles, trust tiers) — already implemented — but not code.

## Cross-Device Stack (3 layers, all using existing infrastructure)

```
┌─────────────────────────────────────────────────────────────┐
│  Phone (Neo/Ego browser)                                    │
│  ┌─────────────┐  ┌─────────────────────────────────────┐   │
│  │ Telegram    │  │ FastAPI UI (http://mac:8080)        │   │
│  │ bridge bot  │  │ (Kanban + chat + analytics)           │   │
│  └─────────────┘  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                        │ Syncthing (5m cadence)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Mac (agent-router host)                                    │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ FastAPI backend (8080)                              │   │
│  │   - /api/chat  — dispatch tasks                     │   │
│  │   - /api/cards — Kanban board                       │   │
│   │  - /api/analytics — token usage                   │   │
│  │   - /api/agents — agent/model status                │   │
│  │   - /api/evaluate/all — PEEM eval                   │   │
│  │                                                       │   │
│  │ Telegram bridge (scripts/telegram_bridge.py)        │   │
│  │   - Send: card summaries, PEEM scores, drift        │   │
│  │   - Receive: /status, /cards, /drift, /dispatch     │   │
│  │                                                       │   │
│  │ Cross-device sync (scripts/cross_device_sync.py)    │   │
│  │   - --status: Syncthing + file health               │   │
│  │   - --council: fan-out research to Oracle VM        │   │
│  │   - --export: state for phone consumption           │   │
│  └─────────────────────────────────────────────────────┘   │
                        │ SSH tunnel (3033:3033)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Oracle VM (oracle-vm:84.8.249.139)                         │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ council.service (127.0.0.1:3033)                    │   │
│  │   - Multi-model fan-out: gemini, glm, gemma, kimi   │   │
│  │   - 80 calls/day cap                                │   │
│  │   - Writes results to vault pages/inbox/llm/        │   │
│  │                                                       │   │
│  │ journal-bot.service (Telegram bot)                  │   │
│  │   - Already running                                 │   │
│  │                                                       │   │
│  │ Vault: /home/ubuntu/memory-vault (Syncthing synced) │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Setup Steps

### 1. SSH Tunnel to Oracle VM (one-time, per session)
```bash
ssh -L 3033:127.0.0.1:3033 -N -f oracle-vm
```

### 2. Set Telegram credentials (one-time)
```bash
export TELEGRAM_BOT_TOKEN=<from @BotFather>
export TELEGRAM_CHAT_ID=<your chat ID>
```

### 3. Start the Telegram bridge (Mac)
```bash
python scripts/telegram_bridge.py --send-only   # test
python scripts/telegram_bridge.py                # poll for commands
```

### 4. Check cross-device health
```bash
python scripts/cross_device_sync.py --status
```

### 5. Fan-out research to Oracle VM council
```bash
python scripts/cross_device_sync.py --council "research question here"
```

## Telegram Commands

| Command | Action |
|---|---|
| `/status` | Router health + agents + models availability |
| `/cards` | Recent open kanban cards |
| `/drift` | Config drift proposals (PEEM feedback) |
| `/dispatch <task>` | Dispatch a task to the router |
| `/analytics` | Token usage analytics |
| `/help` | This message |

## Cross-Device Flow

1. **Mac**: User types task → FastAPI → LangGraph supervisor → agent dispatch → Kanban card + PEEM eval
2. **Telegram**: Bridge sends card summary + PEEM score + drift proposals to phone
3. **Phone**: User replies via Telegram `/dispatch <task>` → router dispatches → result returns to Telegram
4. **Oracle VM**: Council fan-out for deep research (multi-model) → writes to vault pages/inbox/llm/ → Syncthing syncs to Mac
5. **Syncthing**: 5m cadence syncs vault + SQLite between Mac and VM

## Token Optimization (from analytics)

The `get_token_analytics()` method identifies:
- High-token agents (>5000 tokens) that could route to NIM instead
- Per-agent/model/lane breakdown
- Optimization suggestions: "Consider routing X tasks from claude to NIM agents"

## Deterministic Model Selection

The supervisor selects models by:
1. **Availability**: Only models with keys in env + responsive NIM endpoints
2. **Role**: supervisor → triage/reasoning, worker → execution
3. **Task type**: build/review → codex/nim, research → nim3, planner → nim/claude
4. **Drift constraints**: Avoid consistently failing agents/models (PEEM < 3.0)
5. **Fallback**: Deterministic triage when no model available

This ensures the right model for the right task at the right time with minimal token usage.

## What Was NOT Built (and Why)

| Item | Reason |
|---|---|
| Custom React UI | Too much effort; Telegram + existing Hermes UI sufficient |
| Copy from cccc | Different architecture (Rust daemon, Groups); more integration work |
| Docker multi-container | Single-container Dockerfile is sufficient |
| n8n-style visual workflow | Not needed; proactive loop is code-based |
| Keychain storage | Env files + ~/.env are sufficient for single-user |