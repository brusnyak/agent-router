# Agent Router: handoff (2026-11-12, end of session)

Start here in a fresh session. Branch `dev/backbone`, nothing committed or pushed (54+ files staged/untracked; review before committing).

## What exists (all in `backbone/`, 29 tests: `python3 -m pytest tests/test_backbone.py -q`)
| Piece | State | How to check |
|---|---|---|
| Key pool (NIM_1..3, cap 2/key, retry + failover) | works | `python3 -m backbone keys` (under `~/.claude/scripts/with-env NIM_1 NIM_2 NIM_3 --`) |
| Workers: Pi on NIM keys, `@or` = `openrouter/free`, Claude + Codex (own login, one at a time) | works | `python3 -m backbone run "@nim2 ..." --gate "<cmd>"` |
| LangGraph run graph + SQLite checkpoints, `runs resume ID` | works (kill -9 mid-gate then resume re-ran only the gate) | `python3 -m backbone runs resume ID` |
| Library DB (FTS5 + NIM embeddings): 418 skills, 293 agent personas, 13 commands, 2 clips | works | `python3 -m backbone library search "..."`; eval `python3 -m backbone.evalset` |
| Prompt provenance (`prompt_sources` in every result; strong skill hits inject their text) | works | any run result |
| Decision layer `ask` (NIM1 proposes, validation drops invented values; experts opt-in) + advisory critic | works; critic on `openrouter/free` often returns empty | `python3 -m backbone ask "..."` |
| `doctor` (probes each agent) -> `data/capabilities.json` | works | `python3 -m backbone doctor`: claude, codex, kilo, pi usable; qwen, gemini not (auth) |
| `discover` / `init` (writes `~/.agent-router/backbone.yaml`; `init` NOT run yet) | discover works | `python3 -m backbone discover` |
| Remote host dispatch `@host:NAME[:worker]` over ssh | works Mac -> Oracle | needs `hosts:` in config |
| Jobs inbox + daemon (+ GitHub watcher every 6 h), HTTP API `serve` (token), MCP server | work | `jobs`, `daemon`, `serve`, `mcp` |
| Oracle VM: `~/agent-router`, systemd user unit `agent-router`, Pi + Node 22 in `.tools`, `.deps`, keys in `~/.config/agent-router/env` (600) | active; VM not re-synced after the last turn | `ssh oracle-vm systemctl --user is-active agent-router` |

## Measured, not claimed
- Retrieval eval (24 own queries, 724 rows): BM25 top1 0.46 / top3 0.71; hybrid 0.71 / 0.96; rerank no gain (off).
- 20 parallel NIM calls over 3 keys: 20 ok, 7.8 s wall.
- Codex review of the first backend: 9 P1 findings fixed with regression tests.

## Not built / open
Adapters (Telegram, WhatsApp, Nina/Mimoza) via `serve`; browser/research worker (Ego CLI exists, Neo MCP was down); chat UI (design system exists, see below); step-level resume inside a worker; real gate sandbox; patch merge across fan-out workers; GitHub self-improvement loop beyond `watch`; T9 12-task replay (the eval that would justify the scaffold vs NIM alone); `init` never run on a clean HOME (the open-source claim is untested).

## Design system
`DESIGN.md` has 17 tokens; all defined in `ui/src/index.css` with matching hex. 4 off-token hexes in `ui/` (`#1E1E1E #2A2E3A #EF4444 #ffffff`). Router review (unchecked): DESIGN.md says amber for blocked but CSS uses red; `KanbanBoard` imported but not rendered in `App.tsx`; `StatusBar` placement differs from the spec. No browser verification done yet (needs 1440/390 px screenshots viewed by the owner).

## Global Claude config (done by script, backups in `~/.claude/backups-minimize-*`)
Minimal `CLAUDE.md` (1.3 KB) + trimmed Mentor style; context-dumping hooks and the 12 caveman hooks removed; `ANTHROPIC_BASE_URL` removed. Obsidian now opens `memory-vault` (home-dir vault removed from `obsidian.json`).

## Pending owner actions
- `ssh oracle-vm` old project already removed by owner. Install-log lines for VM Node 22 / Pi / langgraph `.deps` not written (denied to the agent).
- Review and commit the staged work on `dev/backbone` yourself.
- Neo: reconnect the browseros-neo MCP in the next session if tab clipping is wanted.

## Next steps (ordered)
1. T9 replay: 12 real tasks x (NIM alone / NIM + router loop / Claude) -> scored table. Kill the scaffold claim if no gain.
2. Fresh-user test: temp `HOME`, one NIM key, `backbone init`, `backbone ask`.
3. UI: serve `ui/`, screenshots 1440 + 390, fix the 4 tokens and layout findings, owner views the screenshots.
4. Browser worker (ego-browser) + clip pipeline into `library` kind `clip` (`data/clips_md/` pattern already works: two YouTube transcripts ingested and retrievable).
5. Adapter over `serve` (copy from Hermes/OpenClaw after reading them).

## Rules for the next session
Backend work only inside this repo; experts (Claude/Codex) only for review, one at a time; no pushes, no spend, no sends without the owner.

## Delegated to Oracle (started 2026-11-12, running unattended)
- **T9-lite replay**: `eval/replay.py --trials 3` on the VM (8 tasks x 2 arms x 3 trials, NIM1 only): single attempt vs router gate-loop. Log `~/agent-router/data/eval/replay.log`, result `~/agent-router/data/eval/replay-*.json` (summary line starts `SUMMARY`). Check: `ssh oracle-vm 'tail -3 ~/agent-router/data/eval/replay.log; ls ~/agent-router/data/eval'`.
  Caveat: tasks are small katas, a ceiling effect (both arms ~100%) means "no evidence either way", not "scaffold useless". The Claude arm and real-repo tasks are still missing.
- **Suits Oracle** (NIM/OpenRouter workers, gate = a command, no subscription login, no secrets): replay evals, test-writing for untested modules, token/lint cleanups in `ui/` (patch for review), scheduled `watch` ingestion, library re-embedding, retrieval eval reruns.
- **Keep on the Mac**: anything needing Claude/Codex logins, Neo/Ego browser, vault writes, git push, the design check you must view.
- **Not set up on the VM**: Claude/Codex, library skill folders (ingest happens on the Mac), git remote.

## 2026-11-12 evening: delegated to Oracle
- Jobs (daemon, Telegram message on finish): aa802712 = SPEC.md for Drizzle triggers plugin in ~/drizzle-triggers (gate: SPEC.md exists, has kill rule + #843); 4e591b9e = tests/test_notify_jobs.py in ~/agent-router (gate: pytest).
- Check: ssh oracle-vm, then in ~/agent-router with env file + PYTHONPATH=.deps: `python3 -m backbone jobs list`.
- Approved by owner: project #3 = Drizzle Postgres triggers plugin (research/L3-scout.md). Kill rule: no outside install/reply in 14 days, or Drizzle ships native triggers.
- Router fixes today: swarm synthesis step, clean no-keys error. Clip ledger now records failure reason (vault scripts/clip_v3.py, backup .bak-20261112).
- Replay result: 24/24 both arms (tie). L3 A/B: router 19 min, 2/3 workers blocked, fabricated output; Claude 4 min; scout agent best. Logs: data/ab/.
- Not done: Mac<->VM sync (git remote), live A/B on owner prompts, outreach U1 day 3 (Fri), clip/CV/brand lanes.

## Unattended-work contract (learned 2026-11-12, each line from a real failure)
- A "done" job = a patch in data/runs/<run>/patch.diff, NOT applied. Harvest: scp the patch, `git apply --check`, run the gate locally, then apply.
- Gate must be scoped to the job's own file (a whole-suite gate blocked on old failures: job 4e591b9e).
- Never rsync config over the VM without checking: it clobbered the pi path (fixed by repo-local `.tools/` fallback in workers.py). `scripts/sync_vm.sh` keeps data/, credentials, .deps, .tools.
- VM submit env: set -a; . ~/.config/agent-router/env; PYTHONPATH=$HOME/agent-router/.deps:$HOME/agent-router; python3 -m backbone submit --cwd <git repo> --gate "<scoped cmd>" "<prompt>".
- Parallel swarm subtasks do not see each other; swarm now ends with a synthesis step (unverified live).
- Telegram: the router project's own bot token is the old lingonberry_trading_bot with a bot as chat id (403). Reports go via Nina's bot, one-way. Two-way needs a dedicated bot: set ROUTER_TG_POLL=1 after owner creates it (backbone/tg.py).
- Outputs from NIM workers are drafts: read before building on them.


## Update 2026-11-12 (evening): spec + M0, M1, M2, M4, M6 built (branch dev/backbone, 37 tests)
Master spec: `docs/AGENT_ROUTER.md` (hub/node, standalone, library kinds, milestones). Scope plan: `docs/E2E-SCOPE-PLAN.md`. Adapter research: `docs/ADAPTER-RESEARCH.md`. Old specs: `docs/archive/`, `docs/appendix/`.
| Milestone | State | Evidence |
|---|---|---|
| M0 evidence check | done | `backbone/evidence.py`; the hallucinated review (5 fake files) now gives `verified=false`, `unverified_reason=cites_missing_file`; field `gate_passed` added |
| M1 library + retrieval | done | 2.1k+ rows, 12 kinds (agent, subagent, skill, command, system, hook, prompt, design, playbook, application, loop, clip), license per row; eval 67 queries: plain hybrid top1 0.64 / top3 0.87, NIM goal-understanding (`understand.expand` + `rerank`) top1 **0.91** / top3 **0.99** (`python3 -m backbone.evalset`) |
| M2 composer + tiers | done | `compose.py`, `understand.analyze`, `tiers:` in config, `python3 -m backbone ask --dry "<raw>"` prints engineered prompt + sources + tier |
| M4 hub/node | built, tested in-process | outbound node client (`backbone node --hub URL --name mac`), `@node:NAME` routing, `/nodes/claim`, `/nodes/result`, offline policy `node_offline: wait|reroute`, Telegram `/nodes` and `/run @node:mac ...`; NOT yet run Mac<->Oracle for real |
| M6 browser worker | done | `browser.py` via Ego, page text fenced as untrusted, `task.finish` cleanup, verified no leaked spaces; `@browser Read <url> ...` |
| Open-source gate | done | test fails on personal paths in tracked code; fresh-HOME `init` wrote config |
Library sources added: ECC agents/commands/rules, VoltAgent subagents + design-md, ai-sales-team playbooks, Anthropic skills + plugins, Piebald extraction of Claude Code system prompts/reminders (MIT), Anthropic prompt-engineering + system-prompt docs scraped via Ego (`~/Developer/refs/anthropic-web`, local-reference licence, never commit).
Known gaps: hooks corpus is only Claude Code reminders (no repo hook scripts indexed); no loop corpus besides the appendix docs; vault has NO proven applications (ledger: 3 rows, 1 acknowledged, 1 rejected, 1 unverified; upwork ledger 22 rows all new/queued); retrieval eval filters by kind (kind-less routing not yet measured); `ask` retrieves twice (resolve + ask).
Not done yet: M3 real-task kill test (3 arms, blind), M5 patch merge, M7 UI check + adapters, M8 init cut + licence audit, Oracle re-sync, Kaggle/BP task.
