# Router decisions (binding; patches must not reverse these without the owner)
- Key pool: no per-key cooldown for ordinary failures (`nim.cooldown_s: 0`); 40 rpm sliding window plus in-flight count; 429 Retry-After still cools that key. (commit d6f93af, d459c67)
- An explicit worker (`--worker`, opts.worker) always overrides the tier/class pick. `--worker X` with `@host:H` means run X on H.
- A Pi timeout is not retried on other keys (3 keys x timeout_s of waste); the task needs a smaller scope.
- Hub nodes are read-only by default (`NODE_ALLOW_WRITE=1` per node, owner decision).
- Fencing: worker writes carry the run's fence; the reaper bumps it; stale writes are rejected (`fenced`).
- Scope: hook-first skill measurement, worktree isolation, durable runs, hub+nodes. Not a gateway (LiteLLM/Portkey/OpenRouter own that). No hosted routers, no auto-install, no auto-archive.
- Delegation is enforced by hooks, not advice. One browser (Lightpanda on the VM), one agent (Nina).
- Mac outreach and posting are on HOLD until the owner lifts it.
## Patch acceptance
Tests pass, no entry above is reversed, the diff is small, and the claimed effect is measured (eval/ or a failing test first). Unmeasured features wait.
- Third party is raw material, not reading: take apart, copy files (pinned, licensed), port, then add one measured improvement. (2026-11-15, owner; skill `harvest-then-improve`)
- Enforcement is redirect-once with the compiled command (PreToolUse Agent|Task); no hard deny; 20% holdout; escape `ROUTER-OK`; cheap model (haiku/sonnet) passes. (2026-11-15)
- Planning/review leader models: modern haiku, sonnet or a codex model. Opus/fable are not used for planning (owner, tested). (2026-11-15)
- The bandit learns only from gate results; no gate, no update. Cap decays instead of freezing. (2026-11-15)
- opencode runs through the local NIM proxy (launchd `local.nim-proxy`, :8787); agy runs read-only through `config/agy-allow.json`. (2026-11-15)
- Push to main only after the full test run, an executor benchmark and an Oracle smoke run. (owner, 2026-11-15)
- Watcher: `backbone digest` snapshots logs hourly (launchd local, cron on Oracle); logs hold hashes and counts, never prompt text. A few days of `~/.agent-router/digest/*.json` answer "is delegation happening". (2026-11-15)
- Nina's delegation: `~/bin/router vm [--gate NAME] [--worker W]` logs each call; her pre_tool_call hook (`router-default.py`) now expires its state after 30 min (before, one router job ever disabled it for good) and blocks the second long command with the exact command to run. Backups `*.bak-20261115`. (2026-11-15)
- Antigravity: persistent CLI allow-list lives in `~/.gemini/config/settings.json`; app preset is TURBO already. Read-only rules only until a write task class needs more. (2026-11-15)
- Nina's SOUL is a 24-line thin layer (Karpathy method, efficiency, hard necessities). The previous 73 lines are kept on demand in `~/.hermes-nina/SOUL-reference.md`; backup `SOUL.md.bak-20261115`. Bandit data comes from the watcher observing our own delegated work, not from synthetic benches. (2026-11-15)
