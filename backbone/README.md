# backbone

Durable multi-worker dispatch for coding agents. One chat in front, many workers behind: NIM keys through the
Pi harness, plus Claude Code and Codex running under your own login. No gateway process.

## Quick start (one NIM key is enough)
```bash
pip install pyyaml mcp            # mcp only needed for the MCP server
export NIM_1=...                  # optional: NIM_2, NIM_3 (names listed in config/backbone.yaml)
npm i -g @earendil-works/pi-coding-agent   # the harness that gives a bare key read/edit/bash tools
# add providers nim1..nim3 to ~/.pi/agent/models.json (baseUrl https://integrate.api.nvidia.com/v1, apiKey "${NIM_n}")
python -m backbone library ingest
python -m backbone run "/build @nim1 create hello.py that prints hi" --cwd ~/some/git/repo --gate "python hello.py"
```

## Commands
| Command | What it does |
|---|---|
| `run "[/command] [#project] [@worker] prompt" --gate CMD` | one task; the router runs the gate, never the model |
| `fanout "a" "b" "c"` | parallel prompts, one NIM key each, isolated worktrees |
| `swarm "goal" -n 3` | planner splits the goal, workers run the parts in parallel |
| `submit "..."` + `daemon` | queue a task; the daemon runs it, survives restarts, writes `data/heartbeat` |
| `runs list|show ID|recover` | inspect runs; recover marks dead runs blocked and writes a ticket |
| `library ingest|search Q|counts` | commands, prompts and skills as rows (SQLite FTS5) |
| `keys` | which keys are present, cooling down, ok/fail counts |
| `mcp` | stdio MCP server: dispatch, submit, fanout, library_search, library_get, run_status, keys_status |

## Dispatch (`backbone dispatch`)

`backbone dispatch [--cwd C] [--project P] [--parallel N] [--workers omp,pi,kilo] [--dry-run] packet.md ...`

Parses each packet, schedules waves so overlapping `Allowed writes` never run together, and runs each packet under a lease
(poll 2 s, 15 min timeout -> `lease_timeout`). Prints one line per packet: `name | worker/key | state | gate | seconds`.
`--dry-run` prints the wave plan only.

## Behaviour you can rely on
- Every run works in a detached git worktree; the result is `data/runs/<id>/patch.diff`, not a claim.
- No gate means `verified: false` and the result says so.
- Two failed attempts escalate to the configured expert (`escalation.expert`), then a ticket is written to `tickets_dir`.
- Keys are env var names in config; values are never stored. Run under `with-env` or a systemd `EnvironmentFile`.

## Safety notes
- `gate` and `cwd` arrive from whatever calls the MCP tool (possibly a model reading untrusted text). Gates run with
  `shell=True` as your user. Treat the MCP server as local-trust only; see SPEC.md section 8.
- Context handling is retrieval + summarisation under a token budget. It does not enlarge a model's window.
