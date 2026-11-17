# Quickstart

agent-router is a lightweight multi-agent router: type one prompt, NIM1 picks the command/project/worker/gate, the router runs it, and a critic reviews. Runs queue through a daemon and keep going after you disconnect.

One command instead of a shell block:

```sh
make                    # show targets
make install            # venv + pip install -r requirements.txt
make doctor             # probe every detected agent (read-only)
make discover           # detect agents, keys, ssh hosts, projects
make init               # write ~/.agent-router/backbone.yaml from discovery

# NIM keys from env; values never printed or stored
make keys               # NIM key status
make run prompt="free text question" worker=nim2
make ask text="free text question"
```

`make install` is the equivalent of `python3 -m venv .venv && pip install -r requirements.txt`.
`make doctor` replaces `python3 -m backbone doctor`, `make run` replaces
`python3 -m backbone run`, etc. All targets are defined in the root `Makefile`.

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
