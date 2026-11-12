# Adapter research: Hermes and OpenClaw (2026-11-12)

Evidence: `gh api` on NousResearch/hermes-agent (26,358 files) and openclaw/openclaw (66,796 files); `ssh oracle-vm systemctl --user list-units`.

- Hermes gateway: `gateway/run.py` facade + `platforms/<name>.py` over `platforms/base.py` (49 platform files). New platform = plugin in `~/.hermes/plugins/<name>/{plugin.yaml,adapter.py}` subclassing `BasePlatformAdapter`, registered via `ctx.register_platform()`, zero core changes (`gateway/platforms/ADDING_A_PLATFORM.md`). Two message guards (base adapter queue + runner) must both pass approval/control commands.
- OpenClaw: one long-lived Gateway owns all channels (Telegram via grammY, WhatsApp via Baileys, ...), typed WebSocket API (`req:agent` -> `res:agent {runId,status:accepted}`), clients/nodes connect over WS; docs `docs/concepts/architecture.md`, `docs/channels/telegram/*`, code `extensions/telegram`.
- Already live on Oracle: `hermes-nina.service`, `hermes-mimoza.service` (Telegram gateways) and `agent-router.service`.

Conclusion: do not port channel code. Attach: Hermes (already on Oracle, already on Telegram) calls the router over `serve` HTTP / MCP, or a ~100-line Hermes plugin posts to `serve`. Router stays the prompt-engineering + delegation backend.
