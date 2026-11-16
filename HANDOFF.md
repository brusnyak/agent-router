# HANDOFF: Agent Router (2026-11-15). Older: `docs/archive/HANDOFF-2026-11-13-shadow-hook.md`

Repo (PRIVATE). Work branch `dev/enforcement`; `main` is pushed only after the release gate below.


## What exists now
- Decision layer: `backbone/{plan,bandit,rules,enforce}.py`, `config/routes.yaml`. See README "Decision layer".
- Enforcement hook (redirect-once on Agent|Task) is installed in `~/.claude/settings.json` (backup `*.bak-20261115-070650-shadowhook`; remove with `python3 scripts/shadow_hook.py uninstall`). Log: `~/.agent-router/enforce.jsonl`.
- Executors that pass a real run: pi on NIM_1..3, claude, codex, jcode, opencode (needs launchd `local.nim-proxy` on :8787), agy (read-only).
- Bandit state: `~/.agent-router/data/bandit.db`; inspect with `python3 -m backbone plan --table`.
- Skill for future agents: `~/.claude/skills/harvest-then-improve`. Retro: `docs/RETRO-2026-11-15.md`. Build prompt: `docs/BUILD-PROMPT-2026-11-15.md`.

## Release gate for main (met 2026-11-15; main pushed, Oracle on main)
1. `pytest -q tests` green. 2. Executor benchmark table in `docs/BENCH-2026-11-15.md`. 3. Oracle: pull main, restart `agent-router*.service`, one gated run on a NIM worker. 4. No secrets in the diff.

## Watching
`~/.agent-router/digest/latest.json` (hourly). Read it after 2-3 days: `enforce.redirects` vs `sessions_redirected`, `nina.router_calls`, `runs` per worker, `bandit` means. Nina side: `~/.hermes-nina/state/router-default.jsonl`, `~/.agent-router/router-calls.jsonl` on Oracle.

## Traps
- Gates need absolute python paths. Isolated worktrees see committed files only.
- jcode costs ~29k input tokens per call; opencode run took ~39 s wall for a one-word task; keep both for parallel or special cases, let the bandit decide.
- agy: headless mode denies unlisted tools. Persistent allow-list = `~/.gemini/config/settings.json` (`permissions.allow`; verified 2026-11-15, copy of `config/agy-allow.json`). The app's own mode is in `~/.gemini/config/config.json` userSettings (preset TURBO, eager auto-exec, already permissive). To approve more tools, append rules like `read_file(*)` to that file; the router worker also passes `--settings config/agy-allow.json`.
- Oracle has no pi/opencode/codex/claude on PATH; only NIM via pi once installed under `.tools/`.
- Fixed 2026-11-15: hub jobs with a named gate crashed silently (`gate_name` leaked into `bb.run`); crashes now land in the job `result`.
