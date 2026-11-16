# Orchestration state (2026-11-16)

Current worker set on Oracle hub + Mac node. `backbone run --worker X` routes through `backbone/graph.py` (LangGraph: prepare → work → check → [critic] → finish).

## Workers

| Worker | Where | How invoked | Status |
|--------|-------|-------------|--------|
| hermes | Oracle | channel gateway (active, loopback `:3033`) | PRIMARY reasoning agent |
| goose | Oracle + Mac | headless CLI on NIM key | KEEP — lightweight tasks |
| codex | Mac only | local binary | fallback/escalation expert |
| claude | Mac only | local binary | fallback/escalation expert |
| pi / jcode / opencode | Mac only | NIM-key CLI workers (not on Oracle) | available |
| openhands | removed | was agent-server `:8000` | REMOVED — too slow, wrong tool |

Hermes config: `config/backbone.yaml` → `hermes { enabled: true, base_url: http://127.0.0.1:3033, delegate_to_backbone: true, backbone_serve_url: http://127.0.0.1:8799, backbone_token_env: BACKBONE_TOKEN }`. OpenHands worker block removed from both Mac and Oracle configs.

Hermes delegates tasks to the backbone router via `~/bin/router vm` (which POSTs to `POST /submit` on `backbone serve`, loopback `:8799`, bearer `BACKBONE_TOKEN`). The daemon (`agent-router.service`) claims pending jobs and runs them through the graph. Verified: `router vm --gate noop --worker goose 'Say ROUTER_VM_OK'` → `DONE` in ~25s.

## Hermes router-delegate skill

Installed at `~/.hermes-nina/skills/router-delegate/SKILL.md` on Oracle. Ranked #1 by the `skill-hint.py` pre_llm_call hook for delegation messages (score 6/6), so Hermes is proactively told to delegate long builds/tests/research to the router. The `router-default.py` pre_tool_call hook prompts router use for second long build/test in a task.

## Graph

`prepare` → `work` → `check` → `critic` → `finish` (gate loop on `work`/`check` when `gate` set).
- `critic`: skepticism layer, config `critic.when` (always|gate|opinion, default `gate`). Re-reviews accepted output via OpenRouter free model; `verdict != pass` sets `verified=false` and blocks `finish` (routes back to `work` while attempts remain). Skipped when `OPENROUTER_API_KEY` unset.
- `verified=false` blocks `done`; `finish` writes `blocked` ticket on failure.

## Topology

Oracle = always-on hub (hermes gateway `:3033`, backbone serve `:8799` loopback, backbone daemon). Mac = dev node, outbound SSH tunnel only to hub port 8799; nothing on Mac listens for Oracle. Cross-host: `backbone run --worker host:oracle-vm:X` runs X on Oracle.

## NVIDIA API key status — RESOLVED

All three Oracle NIM keys were stale (HTTP 403). Copied the working Mac keys (`~/.env` NIM_1/NIM_2/NIM_3) to Oracle's `backbone.service` EnvironmentFile and restarted `backbone.service`. All three now return HTTP 200 from `https://integrate.api.nvidia.com/v1/chat/completions`, and `backbone serve /v1/chat/completions` returns completions (verified: "KEYS_OK").

No 4th key needed at this time. If Hermes needs dedicated rate-limit isolation later, add NIM_4 to `config/backbone.yaml` → `nim.keys` and the Oracle `backbone.service` EnvironmentFile.

## Open notes

- Delegation path fully wired: `~/bin/router vm` → `POST /submit` on backbone serve → daemon claims job → runs through LangGraph → state `done`/`blocked`. Hermes skill `router-delegate` teaches Hermes when/how to delegate; `router-default.py` hook prompts router use for second long build/test.
- Hermes gateway source is at `~/hermes-source` on Oracle; its API contract for accepting tasks from backbone needs to be wired (gateway currently returns `{"error": "not found"}` for generic paths — it's a messaging gateway, not a task API). Delegation works from Hermes→router via `router vm`, not yet from router→Hermes.
- OMP (can1357/oh-my-pi): not in DataCamp top-10 harnesses, worse benchmarks than Pi, not installed on Oracle, own provider model — not a viable substitute. Not pursued.
- agent-router.service fix: `WorkingDirectory=%h/agent-router` pointed to nonexistent dir; changed to `%h/Developer/agent-router`; daemon now active.
