# Running agent-router on Oracle through Hermes

Written 2026-11-13 from local files only. No ssh, no network and no VM access was used. Anything not confirmed locally is under "UNKNOWN / needs owner". Env var NAMES only, never values.

## What Hermes is (what the repo says; the vault pages were NOT read)
- Hermes Agent is an MIT-licensed channel gateway. `docs/COMPONENTS.md` line 28: "Hermes already on Oracle: integration target, not a dependency".
- `backbone serve` is described as a "loopback HTTP API for adapters (Telegram, Hermes, UI); needs BACKBONE_TOKEN" (`backbone/cli.py:47`). So Hermes talks to this project through that HTTP API.
- On the Mac, Hermes config is `~/.hermes` and there is a skill `~/.claude/skills/hermes-change/SKILL.md` and a project `hermes-ui` (`~/hermes-ui`) in `config/projects.yaml`. Contents of that skill and of any vault page: UNKNOWN (access not granted in this session).
- Not to be confused with `kerpopule/hermes-jev-skills` (a separate decision-model repo, study only, do not adopt).

## How Oracle is reached and how code is synced (from `scripts/sync_vm.sh`)
- SSH host alias: `oracle-vm` (alias only; real hostname/IP: UNKNOWN). Remote dir: `agent-router/` under the remote home.
- Sync is one way, Mac to Oracle: `scripts/sync_vm.sh [--dry] [--restart]`. It is `rsync -az --delete` and excludes `data/`, `.tools/`, `.env*`, `.deps/`, `.git/`, `__pycache__/`, `node_modules/`, `*.db*`, `.pytest_cache/`.
- `--restart` runs `systemctl --user restart agent-router` on the VM and checks `is-active`. So a user systemd unit named `agent-router` is expected there (its unit file: UNKNOWN).
- Always run `scripts/sync_vm.sh --dry` first. `--delete` removes remote files that are not on the Mac (except the excluded ones).
- `.venv/` is NOT excluded: syncing would push the Mac virtualenv (wrong platform; the VM is aarch64 Linux per `docs/STACK.md`). Whether the VM uses `.deps/` instead is UNKNOWN. Check with `--dry` before the first real sync.
- The repo is not on the VM through git (`.git/` excluded, nothing pushed).

## Which pieces run on Oracle
| Piece | On Oracle? | Notes |
|---|---|---|
| `backbone daemon` (jobs queue; `--poll`, `--parallel`) | yes, via the `agent-router` service | needs NIM keys |
| `backbone serve --port 8799` (loopback HTTP, hub) | yes | needs `BACKBONE_TOKEN`; loopback only, reached by tunnel |
| `scripts/nightly.sh` (build_catalog, shadow_enrich, librarian, hook_log report) | possible, not set up | reads `~/.claude` skills and receipts which are on the Mac; run it where those files are, or copy them |
| `eval/shadow_enrich.py`, `eval/librarian.py` | possible | inputs are Mac data (receipts, catalog, `~/.claude`); on the VM they would see nothing unless synced |
| tests | yes | `python -m pytest tests -q` in the background; 2 legacy tests need a real NVIDIA key |

## What stays on the Mac
- Hook registration (`~/.claude/settings.json`, `python3 scripts/shadow_hook.py install|uninstall|status`). The hooks run inside Claude Code sessions, which are on the Mac.
- Transcripts (`~/.claude/projects`), receipts (`~/.agent-router/hook-shadow.jsonl`), held-out data (`eval/heldout*`, gitignored, private). Do not sync them to the VM without an owner decision.
- Orca, Claude and Codex logins, the vault (`~/memory-vault`).

## Outbound-only hub / node (from `backbone node`)
- Hub = Oracle (`backbone serve`, loopback `127.0.0.1:8799`). Node = the Mac.
- Command on the node: `.venv/bin/python -m backbone node --hub http://127.0.0.1:8799 --name <NAME>`. The help text says to reach the hub "through an ssh -L tunnel", so the Mac opens `ssh -L 8799:127.0.0.1:8799 oracle-vm` and the node connects outbound. Nothing on the Mac listens for the VM.
- Address a job to a node with `@node:NAME` in the prompt. The node claims the job and runs it locally.
- Proven only in-process (HANDOFF). A real Mac<->Oracle run has never been done.

## Env var NAMES
- `NIM_1`, `NIM_2`, `NIM_3` (NVIDIA keys, `config/backbone.yaml`)
- `BACKBONE_TOKEN` (serve and node auth)
- `ROUTER_BOT_TOKEN` (Telegram bot; alt: credential `TELEGRAM_BOT_TOKEN`)
- `ROUTER_NODE`, `ROUTER_TG_POLL`, `BACKBONE_NO_SECRETS_FILE`, `HOOK_LOG`, `MR_ORCH_DISPATCH`, `OPENROUTER_API_KEY` (optional; found in `backbone/*.py`, meaning not re-checked)
- The VM keeps its own credentials file (`sync_vm.sh` comment); its path: UNKNOWN.

## First-run checklist
1. `scripts/sync_vm.sh --dry`; read the list; confirm `.venv` and `data/` handling.
2. Owner approves the real sync (a push to a third-party host).
3. On the VM: python version (3.12 per STACK.md), `pip install -r requirements.txt`, run `python -m pytest tests -q` in the background.
4. Set the env var names above through the VM's own secret mechanism (UNKNOWN which).
5. `systemctl --user status agent-router`; then `backbone serve` health check on loopback.
6. Open the tunnel from the Mac, start the node, send one `@node:NAME` job with a harmless prompt.
7. Install onnxruntime/numpy only if the embedder is needed (STACK.md: not installed yet; the hook does not need them).
8. Confirm the Hermes adapter calls `serve` with the token. Adapter location: UNKNOWN.

## Rollback
- Stop: `systemctl --user stop agent-router` (on the VM).
- Code: re-run `scripts/sync_vm.sh` from the previous Mac commit state; the VM has no git, so keep a tarball of the VM `agent-router/` before the first `--delete` sync.
- Mac hooks: `python3 scripts/shadow_hook.py uninstall` (backup `settings.json.bak-*-shadowhook` is made first).
- Node: kill the `backbone node` process and the `ssh -L` tunnel.
- Data on the VM (`data/`, `*.db*`) is never touched by the sync.

## UNKNOWN / needs owner
- Real hostname, user, port, key of `oracle-vm` (only the alias is known).
- What Hermes does on the VM, how it is started, its config path, its API contract with `serve`. The skill `hermes-change` and the vault pages were not readable in this session; read them first.
- The `agent-router` systemd unit: its ExecStart (daemon or serve or both), working dir, env file.
- Whether the VM has its own venv or `.deps/`; whether `.venv/` is being rsynced today.
- Where the VM credentials file lives and which secret names it holds.
- Whether the nightly job should run on the VM (needs Mac data) or stay on the Mac (needs a scheduler: launchd/cron, not set up).
- Whether Hermes is allowed to submit jobs that run workers (spend, third-party sends need owner approval).
- Telegram inbound on the VM (bot is paired; inbound needs the daemon running).
