# Quickstart

agent-router is a lightweight multi-agent router: type one prompt, NIM1 picks the command/project/worker/gate, the router runs it, and a critic reviews. Runs queue through a daemon and keep going after you disconnect.

## Install

- Python 3.12 (minimum version unverified)
- `pip install -r requirements.txt` (file contents unverified)
- Export NIM keys — env var names from config/backbone.yaml (`nim.keys`); values are never stored:

export NIM_1=...
export NIM_2=...
export NIM_3=...

## First run

python3 -m backbone doctor      # probe every detected agent (uses your logins briefly)
python3 -m backbone ask "free text question"
python3 -m backbone run "/build #proj @nim2 prompt"
python3 -m backbone submit "/build #proj @nim2 prompt"   # queue for daemon
python3 -m backbone daemon      # runs queued tasks (poll 5.0 s, parallel 2)

Commands verified in `backbone [-h] usage`: doctor, ask, run, submit, daemon.

## Where results land

- `data/backbone.db` — durable run table
- `data/runs/` — run records
- `data/tickets/` — failed runs become tickets (`<run-id>.md`, status blocked)
After `python3 -m backbone init`, paths live under `~/.agent-router/` (exact mapping unverified).

## Add a worker

Edit `~/.agent-router/backbone.yaml` (written by `init`) and add under `workers:`:

workers:
  <name>: {cmd: <binary>, timeout_s: <seconds>}

Built-in workers: pi, claude, codex.

## Unverified

- minimum Python version, requirements.txt contents
- results path after `init`, OpenCode/Zed MCP wiring, ACP agent, Telegram/Hermes adapters
