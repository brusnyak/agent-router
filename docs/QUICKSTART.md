# Quickstart

Agent Router is an environment-aware control plane: discover your tools, generate
local config, route tasks to workers, verify outcomes, and persist jobs in SQLite.
One command instead of a shell block:

```bash
make                    # show targets
make install            # venv + pip install -r requirements.txt
make discover           # inventory CLIs, keys, projects, SSH hosts
make init               # write ~/.agent-router/backbone.yaml (non-destructive)
make doctor             # probe workers (read-only)

# Explore without executing an agent
make compile text="Fix failing tests in my project"

# Run a worker (may consume account allowance)
make run prompt="Review this project" worker=codex gate="noop"

# Submit eligible vault tickets to the existing queue
make tickets [dir=~/vault/pages/jobs]
```

`make install` is the equivalent of `python3 -m venv .venv && pip install -r requirements.txt`.
`make doctor` replaces `python3 -m backbone doctor`, `make run` replaces
`python3 -m backbone run`, etc. All targets are defined in the root `Makefile`.

`init` is non-destructive: it refuses to overwrite an existing `backbone.yaml`.

## Where results land

- `data/backbone.db` — durable run table
- `data/runs/` — run records
- `data/tickets/` — failed runs become tickets (`<run-id>.md`, status blocked)

After `python3 -m backbone init`, paths live under `~/.agent-router/`.

## Add a worker

Edit `~/.agent-router/backbone.yaml` (written by `init`) and add under `workers:`:

```yaml
workers:
  <name>: {cmd: <binary>, timeout_s: <seconds>}
```

Built-in adapters: Pi, Claude Code, Codex. Any other discovered CLI runs through
the `generic` adapter (argv-only, allowlisted, bounded); detection alone does not
imply execution support.

## Verified commands

`backbone [-h] usage` confirms: doctor, ask, run, submit, daemon.

## Unverified

- minimum Python version, requirements.txt contents
- exact results path after `init`, OpenCode/Zed MCP wiring, ACP agent,
  Telegram/Hermes adapters, real host-to-host hub/node smoke test
