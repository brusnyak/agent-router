# Orchestration state (2026-11-16)

Current worker set on Oracle hub + Mac node. `backbone run --worker X` routes through `backbone/graph.py` (LangGraph: prepare → work → check → [critic] → finish).

## Workers

| Worker | Where | How invoked | Status |
|--------|-------|-------------|--------|
| hermes | Oracle | channel gateway `:3033` + API server `:8642` | PRIMARY reasoning agent |
| goose | Oracle + Mac | headless CLI on NIM key | KEEP — lightweight tasks |
| codex | Mac only | local binary | fallback/escalation expert |
| claude | Mac only | local binary | fallback/escalation expert |
| pi / jcode / opencode | Mac only | NIM-key CLI workers (not on Oracle) | available |
| openhands | removed | was agent-server `:8000` | REMOVED — too slow, wrong tool |

Hermes config: `config/backbone.yaml` → `hermes { enabled: true, base_url: http://127.0.0.1:3033, delegate_to_backbone: true, backbone_serve_url: http://127.0.0.1:8799, backbone_token_env: BACKBONE_TOKEN }`. OpenHands worker block removed from both Mac and Oracle configs.

## Bidirectional delegation (fully wired)

**Hermes → router:** `~/bin/router vm --gate NAME --worker W "task"` POSTs to `POST /submit` on `backbone serve` (loopback `:8799`, bearer `BACKBONE_TOKEN`). The daemon (`agent-router.service`) claims pending jobs and runs them through the graph. Verified: `router vm --gate noop --worker goose 'Say ROUTER_VM_OK'` → `DONE` in ~25s.

**Router → Hermes:** Hermes API server (`hermes_cli.main gateway run`) exposes OpenAI-compatible endpoints on loopback `:8642`:
- `POST /v1/chat/completions` — stateless chat (opt-in session via `X-Hermes-Session-Id`)
- `POST /v1/runs` — start a run, returns `run_id` (202); `GET /v1/runs/{id}` for status; `GET /v1/runs/{id}/events` for SSE
- `GET /v1/models` — lists `hermes-agent`
- `GET /health` — health check
Auth: `Authorization: Bearer <API_SERVER_KEY>`. `API_SERVER_ENABLED=true` + `API_SERVER_KEY` set in `~/.config/agent-router/env`, loaded via `EnvironmentFile` in `hermes-nina.service`. `api_server` platform added to `~/.hermes-nina/config.yaml`. Verified: health returns `{"status":"ok","platform":"hermes-agent","version":"0.19.0"}`; `/v1/runs` returns a run_id.

## Hermes router-delegate skill

Installed at `~/.hermes-nina/skills/router-delegate/SKILL.md` on Oracle. Ranked #1 by the `skill-hint.py` pre_llm_call hook for delegation messages (score 6/6), so Hermes is proactively told to delegate long builds/tests/research to the router. The `router-default.py` pre_tool_call hook prompts router use for second long build/test in a task.

## Graph

`prepare` → `work` → `check` → `critic` → `finish` (gate loop on `work`/`check` when `gate` set).
- `critic`: skepticism layer, config `critic.when` (always|gate|opinion, default `gate`). Re-reviews accepted output via OpenRouter free model; `verdict != pass` sets `verified=false` and blocks `finish` (routes back to `work` while attempts remain). Skipped when `OPENROUTER_API_KEY` unset.
- `verified=false` blocks `done`; `finish` writes `blocked` ticket on failure.

## Topology

Oracle = always-on hub (hermes gateway `:3033` + API server `:8642`, backbone serve `:8799` loopback, backbone daemon). Mac = dev node, outbound SSH tunnel only to hub port 8799; nothing on Mac listens for Oracle. Cross-host: `backbone run --worker host:oracle-vm:X` runs X on Oracle.

## NVIDIA API key status — RESOLVED

All three Oracle NIM keys were stale (HTTP 403). Copied the working Mac keys (`~/.env` NIM_1/NIM_2/NIM_3) to Oracle's `backbone.service` EnvironmentFile and restarted `backbone.service`. All three now return HTTP 200 from `https://integrate.api.nvidia.com/v1/chat/completions`, and `backbone serve /v1/chat/completions` returns completions (verified: "KEYS_OK").

No 4th key needed at this time. If Hermes needs dedicated rate-limit isolation later, add NIM_4 to `config/backbone.yaml` → `nim.keys` and the Oracle `backbone.service` EnvironmentFile.

## Open notes

- Delegation fully wired both directions: Hermes→router via `router vm` → `/submit`; router→Hermes via API server `:8642` (`/v1/chat/completions`, `/v1/runs`). Hermes skill `router-delegate` teaches Hermes when/how to delegate; `router-default.py` hook prompts router use for second long build/test.
- OMP (can1357/oh-my-pi): not in DataCamp top-10 harnesses, worse benchmarks than Pi, not installed on Oracle, own provider model — not a viable substitute. Not pursued.
- agent-router.service fix: `WorkingDirectory=%h/agent-router` pointed to nonexistent dir; changed to `%h/Developer/agent-router`; daemon now active.
- hermes-nina.service fix: added `EnvironmentFile=/home/ubuntu/.config/agent-router/env` so `API_SERVER_ENABLED`/`API_SERVER_KEY` are loaded; added `api_server` platform to `~/.hermes-nina/config.yaml`.
