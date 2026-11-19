# FINALIZE-PLAN — agent-router backbone

Produced via `backbone run "@pi"` through the router (worker `pi:NIM_1`), read-only report saved here.

## 1. Kill switch — confirmed working

`backbone guard status|pause|resume` exists in `backbone/guard.py` `main()`, wired in `backbone/cli.py` under the `guard` subparser.
- `pause` writes `~/.agent-router/PAUSE`; `resume` removes PAUSE files; `status` prints JSON (pause file, unattended flag, today's ledger counts).
- It blocks all dispatch: `Backbone.run`, `fanout`/`swarm`/`delegate`, daemon `_claim`, node `bb.run`, `serve /submit`, remote host dispatch.
- Gap: `serve /v1/chat/completions` (direct `nim.chat`) is chat, not a worker dispatch path, so not guard-gated. That's acceptable.

## 2. Single "stop everything" command

`backbone guard pause` — fail-closed kill file, no new dispatches anywhere. It does not kill running loops. To fully halt: stop hub (`backbone serve`), daemon, and node as OS processes (Ctrl+C, `pkill -f "backbone"`, or stop systemd units). In-flight runs finish or time out.

Sync to Oracle: the router has no push-to-Oracle sync yet. The node polls the hub outbound (no inbound port); Hermes on Oracle calls the local hub via `serve`. Stop the Oracle node process to stop its polling; `guard pause` stops hub-side dispatch.

## 3. Free-model workers (no paid credits)

- **kilo**: headless. `kilo run <message> --pure`; leased NIM/OpenAI-compatible key via env (`API_KEY`); model `nim/NIM_n`. Works with free NIM keys. *Note: kilo `run` needs session handling for reliable headless router dispatch — verified interactive; headless needs `--session` flags.*
- **opencode**: headless. `--standalone run --auto`; leased NIM key via env; provider pinned to NVIDIA NIM base URL. Works with free NIM keys.
- **cline**: headless-capable (`cline --plan --cwd DIR PROMPT`) but bound to the owner's installed binary + login; NIM routing requires explicit `--provider nvidia|nim --model <model>` flags, otherwise it uses the owner's subscription (paid credits).

## 4. Config hygiene — clean

`config/backbone.yaml`: keys appear only as env names (`NIM_1`..`NIM_5`); values loaded at runtime from `~/.env` / `~/.config/agent-router/env` (`backbone/keys.py load_named`, `KeyPool`), never printed or stored. Paths use `~` (expanded at runtime) or relative. `library.sources` includes `~/.claude/skills` (per-user tilde). `vault_query: ${VAULT_QUERY_PATH:-...}` env substitution. `hosts: {}`. No hard-coded secrets, no absolute owner paths.

## 5. Minimum push → clean re-clone → discover/init/keys/test/run gate=noop

1. `git add -A && git commit -m "foundation complete" && git push origin dev/backbone` (exclude `.venv/`, `data/`, secrets files)
2. `git clone https://github.com/brusnyak/agent-router.git && cd agent-router`
3. `python3.13 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && .venv/bin/pip install -q -e .` (installs the `backbone` console script)
4. Place NIM key values in `~/.env` or `~/.config/agent-router/env` (names only enter config)
5. `backbone discover` — review agent/key/SSH/project inventory
6. `backbone init` — writes `~/.agent-router/backbone.yaml`; review before running jobs
7. `with-env NIM_1 NIM_2 NIM_3 -- backbone keys` — key presence check, values hidden
8. `.venv/bin/python -m pytest tests -q` — test suite
9. `with-env NIM_1 -- backbone run "smoke" worker=nim1 gate=noop` — `noop` gate is `true` in config `gates:`, always passes
