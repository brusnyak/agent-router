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
