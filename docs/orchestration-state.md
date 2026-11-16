# Orchestration state (2026-11-16)

Current worker set on Oracle hub + Mac node. `backbone run --worker X` routes through `backbone/graph.py` (LangGraph: prepare → work → check → [critic] → finish).

## Workers

| Worker | Where | How invoked | Status |
|--------|-------|-------------|--------|
| hermes | Oracle | channel gateway (active, loopback `:3033`) | PRIMARY reasoning agent |
| goose | Oracle + Mac | headless CLI on NIM key | KEEP — lightweight tasks |
| codex | Mac only | local binary | fallback/escalation expert |
| claude | Mac only | local binary | fallback/escalation expert |
| pi / jcode / opencode | Oracle + Mac | NIM-key CLI workers | available |
| openhands | removed | was agent-server `:8000` | REMOVED — too slow, wrong tool |

Hermes config: `config/backbone.yaml` → `hermes { enabled: true, base_url: http://127.0.0.1:3033, delegate_to_backbone: true, backbone_serve_url: http://127.0.0.1:8799, backbone_token_env: BACKBONE_TOKEN }`. OpenHands worker block removed from both Mac and Oracle configs.

Hermes delegates tasks to the backbone router via `POST /submit` on `backbone serve` (loopback `:8799`, bearer `BACKBONE_TOKEN`). The daemon (`agent-router.service`) claims pending jobs and runs them through the graph. Verified: goose job submitted via `/submit` reached state `done`.

## Graph

`prepare` → `work` → `check` → `critic` → `finish` (gate loop on `work`/`check` when `gate` set).
- `critic`: skepticism layer, config `critic.when` (always|gate|opinion, default `gate`). Re-reviews accepted output via OpenRouter free model; `verdict != pass` sets `verified=false` and blocks `finish` (routes back to `work` while attempts remain). Skipped when `OPENROUTER_API_KEY` unset.
- `verified=false` blocks `done`; `finish` writes `blocked` ticket on failure.

## Topology

Oracle = always-on hub (hermes gateway `:3033`, backbone serve `:8799` loopback, backbone daemon). Mac = dev node, outbound SSH tunnel only to hub port 8799; nothing on Mac listens for Oracle. Cross-host: `backbone run --worker host:oracle-vm:X` runs X on Oracle.

## NVIDIA API key status — ACTION REQUIRED

All three Oracle NIM keys return HTTP 403 Forbidden from `https://integrate.api.nvidia.com/v1/chat/completions` (verified directly with curl, not just via backbone). This breaks:
- `backbone serve /v1/chat/completions` (completion failed: http 403 on NIM_2)
- RAG embeddings ("embed http 403")
- Any NIM-backed worker (pi, goose, jcode, opencode)

Keys on Oracle (from `backbone.service` EnvironmentFile): NIM_1, NIM_2, NIM_3 — all dead.
Mac has different keys in `~/.env` (NIM_1, NIM_2, NIM_3) — not yet tested on Oracle.

**Recommendation:** Create a 4th NVIDIA API key (NIM_4) dedicated to Hermes on Oracle for reliability and multi-agent delegation. Add it to `config/backbone.yaml` → `nim.keys` and to the Oracle `backbone.service` EnvironmentFile. Until keys are valid, Hermes reasoning and all NIM workers are non-functional on Oracle.

## Open notes

- Delegation path proven: `POST /submit` on backbone serve creates a job, the daemon claims and executes it, state transitions to `done`/`blocked`. Hermes can use this path for task delegation.
- Hermes gateway source is at `~/hermes-source` on Oracle; its API contract for accepting tasks from backbone needs to be wired (gateway currently returns `{"error": "not found"}` for generic paths — it's a messaging gateway, not a task API).
- OMP (can1357/oh-my-pi): not in DataCamp top-10 harnesses, worse benchmarks than Pi, not installed on Oracle, own provider model — not a viable substitute. Not pursued.
- agent-router.service fix: `WorkingDirectory=%h/agent-router` pointed to nonexistent dir; changed to `%h/Developer/agent-router`; daemon now active.
