# agent-router SPEC (2026-11-12, draft for owner review)

Supersedes SCOPE.md where they differ. Every component has one command that passes or fails. "Proven" means run this session; everything else is a hypothesis with a test.

## 0. Status 2026-11-12 (backend built in `backbone/`, 9 unit tests, `tests/test_backbone.py`)
| Component | State | Evidence (this session) |
|---|---|---|
| Key policy (3 NIM keys, cap 2/key, retry + failover, cooldown) | PROVEN | T3: 20 parallel calls, 20 ok, 7.8 s wall, median 2.3 s |
| Pi workers on NIM1/2/3 with router-run gate + isolated worktree + patch | PROVEN | `/build @nim2 ...` verified in 9.8 s; fanout 3 keys in parallel |
| Claude / Codex as local experts (own login, no API key) | PROVEN | both completed a gated task (5.8 s / 12.7 s) |
| Planner -> parallel workers (`swarm`) | PROVEN, slow | 3 subtasks on 3 keys, 20 to 70 s each (NIM cold/queue) |
| Library DB (114 rows, FTS5), commands as data | PROVEN, lexical only | `library search`; ranking is BM25, not semantic |
| Session context: fold + retrieval + budgeted pack | PROVEN once | folded 8 turns to a 60-token summary keeping all 4 decisions |
| Durable run table, lease, tickets, job inbox + daemon | PROVEN | kill -9 -> `runs recover` -> ticket; submit -> daemon -> done |
| MCP server (6 tools + submit) for OpenCode / Orca / Zed | PROVEN with a python MCP client | OpenCode/Zed wiring unverified |
| Oracle VM copy (`~/agent-router-bb`, Python 3.12) | PROVEN tests only | 9/9 pass on VM; no keys, no Pi, no experts there yet |
2026-11-12 later: run loop is now a LangGraph graph (prepare->work->check->finish) with a SQLite checkpointer; `runs resume ID` continues after a crash without repeating completed steps (killed mid-gate, resumed: only the gate re-ran). Hybrid RAG: BM25 + NIM embeddings (nemotron-3.5-embed-1b) fused by RRF; 114 rows embedded; 2 of 3 spot queries put the right skill first, the third at rank 4. Router-owned style injection, loop-vs-single by gate, config hooks, `@or` OpenRouter free reviewer. VM: systemd daemon + Pi + langgraph, 21 tests pass there. Global Claude config minimized (`scripts/minimize_global.py`).
Later 2026-11-12: library 724 rows (418 skills incl. ECC + marketing, 293 agent personas, 13 commands) all embedded. Retrieval eval (`python -m backbone.evalset`, 24 own queries, 724-row corpus): BM25 top1 0.46 / top3 0.71; hybrid 0.71 / 0.96; rerank no gain (off). Built by the router itself (NIM workers, my tests as gates, Codex-style review via `/review`): `watch.py` (GitHub change poll -> pull -> ingest -> embed, daemon every 6 h), `rerank.py`. Added loopback HTTP API (`serve`, bearer token, named gates) as the attach point for Telegram/Hermes adapters, reasoning commands `/roast` `/next-steps` `/product-critic`, `deploy/agent-router.service`. `/roast` by the 550B model found 3 real issues and 3 wrong ones; `/next-steps` on NIM1 gave stale advice (read old README): reasoning commands need the same gate discipline.
Not done: ACP agent, patch merge across fan-out workers, expert dispatch from the VM, GitHub watcher/self-improvement loops, browser workflows, messaging adapters, Mac<->Oracle delegation.
Archon is no longer on the critical path (D7 resolved: router owns the run table); keep it as an optional executor.

## 1. Goal (owner words, condensed)
One place to type. The router picks the project, the command, the prompt, the skill, the model and the harness; fans work out to NIM1/NIM2/NIM3 and escalates to Claude, Codex, Qwen, Kilo or OpenCode when needed. Runs keep going on a server when the owner stops. Failed runs become vault tickets and retry differently. Light, open source, shareable.

Non-goals: own IDE, own key-rotation gateway, multi-user SaaS, routing Claude/Codex subscription logins on behalf of anyone else.

## 2. Decisions
| # | Decision | Why (evidence) |
|---|---|---|
| D1 | Brain = this repo, Python (existing resolver `router.py`, `prompt_library.py`, `evaluation.py`). The archived LangGraph supervisor stays archived. | SCOPE: supervisor fabricated results. |
| D2 | Executor = a harness per worker; the router fans out, harnesses never spawn their own sub-agents. | OpenCode sub-agent failure reports (anomalyco/opencode #29616, closed not planned); NVIDIA forum: malformed NIM tool-call JSON through OpenCode. |
| D3 | NIM workers run through Pi, each key a separate Pi provider (`nim1..nim3`, `${NIM_n}` env refs). No gateway. | PROVEN: nim-direct 25 s, nim-fanout 3 keys in parallel 44 s, both $0, bash gates passed. |
| D4 | Key policy table: NIM1 default, NIM2/NIM3 sub-agent slots, max 2 concurrent per key, retry once with backoff on 503/timeout, then next key. | Measured earlier: 16 queue-budget 502 + 3 safety 503 of 65 calls via OmniRoute; direct NIM_1 6 parallel calls all 200 in ~0.6 s; cold node took 41 s. |
| D5 | Experts = `claude -p`, `codex exec` run locally by the owner's own installed binary and own login, one task at a time, never token extraction or forwarding. API keys if the owner prefers. | Anthropic legal page (re-fetched): third parties may not "route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users"; own-binary personal use is a gray zone. Owner decides (section 7). |
| D6 | Other agents (Qwen `qwen -p`, Kilo `kilo run --auto`, OpenCode `opencode run`) are optional adapters behind the same interface, added only after T5. | Headless modes documented by researcher; custom-base-URL fit unverified. |
| D7 | Workflow engine = Archon as executor behind an adapter; durable layer = router-owned SQLite run table + systemd on the VM. | Archon crash-resume: `kill -9` leaves run `running`; `resume` refuses it; `run --resume` found nothing at 34 s (stale threshold unknown). See T2. |
| D8 | Server = Oracle Always Free A1 VM. Vercel rejected. | Vercel Hobby is non-commercial and functions cap at 300 s; Oracle official free allowance reads 2 OCPU / 12 GB (blogs say 4/24, unconfirmed); idle reclaim if p95 CPU, network and memory all under 20% for 7 days, so run a heartbeat. |
| D9 | Mac <-> VM sync: Syncthing for markdown tickets and config only; SQLite lives on the VM only (single writer). | Syncthing forum: do not sync live databases. |
| D10 | Surface v1: small chat endpoint (CLI first) + Archon console for runs. Surface v1.5: router as an ACP agent so Zed hosts the chat with editor, tree, terminal. | ACP lists ~51 agents; Zed hosts several; ACP does not pool keys; "router as ACP agent" has no shipped example (unverified). Archon console has no file/diff/terminal (README, deps list). |
| D11 | Second brain = existing vault `query.py` as a retrieval tool for packets. No new RAG. | Already installed and queried this session. |
| D12 | Global Claude rules: minimal profile `~/.claude-min` (8-line CLAUDE.md, Mentor style, karpathy/caveman/ponytail skills, no hooks). Swap in only after T7. | 35 KB rule text + 38 hooks in the current profile. |

## 3. Command grammar (deterministic first, classifier second)
`[/command] [#project] [@worker] prompt`
- `/plan /build /review /research /fix /job` pick a workflow + tier. `#project` picks a registered project. `@nim2|@claude|@codex|@qwen` forces a worker.
- Missing parts: a NIM1 classifier call fills them; the result is logged and shown, never silent.
- Every task runs `router.py find`; hits >= 0.35 go into the packet; an ignored hit is a failed check.
- Packet = owner's words verbatim, hard stops, output contract, acceptance command the router (not the model) runs.

## 4. Loops, hooks, autonomy
- Goal = objective + acceptance command + budget (iterations, wall time, tool calls).
- Loop = work -> router runs gate -> pass: done; fail twice: escalate to expert; fail again: ticket.
- Hooks are router events in Python: `pre_dispatch`, `post_step`, `on_fail`. No dependence on any vendor's hook system.
- Ticket on stop/fail: `vault/tickets/<run-id>.md` (run, step, error, strategy, status=blocked). Retry reads the ticket and changes the plan (smaller scope, other model); never blind replay. Mac writes new files only.

## 5. Tests (each: command, pass condition)
| T | Check | Pass |
|---|---|---|
| T1 | PROVEN `nim-direct`, `nim-fanout` (scratchpad `nim-direct/.archon/workflows/`) | bash gate passes, no gateway running |
| T2 | Archon crash recovery: start run, `kill -9`, wait N minutes, `archon workflow run <wf> --resume` | run finishes without re-running completed nodes; else D7 router-owned table is mandatory and Archon is per-step only |
| T3 | 20 parallel NIM calls across 3 keys through the key policy | <= 2% failures after retry/failover |
| T4 | Router fan-out: one task, planner NIM1, 2 workers NIM2/NIM3, router-run gate | gate passes, trace logged |
| T5 | `codex exec`, `claude -p`, `qwen -p` each complete one gated task from the router adapter | gate passes per agent; Qwen NIM base URL accepted or noted |
| T6 | ACP echo agent registered in Zed `agent_servers` | message round trip in Zed panel |
| T7 | A/B replay: 5 past prompts, current vs `~/.claude-min` | reply length and tool-output completeness table |
| T8 | VM: systemd unit, `kill -9` worker, restart | run resumes from last step; heartbeat visible in vault |
| T9 | Replay set 12 tasks x arms (NIM alone / NIM + router loop / Claude) | scored table; kill the router build if no gain |

## 6. Build order
1. Key policy + Pi provider config in repo (`config/keys.example.yaml`), T3.
2. Run table (SQLite) + adapter for Archon and `claude -p`/`codex exec`, T2, T4, T5.
3. Command grammar + resolver wiring + prompt packets.
4. Ticket writer + heartbeat + VM deploy, T8.
5. ACP agent, T6. Replay set, T9.
6. Open-source cut: example configs, README quickstart with one NIM key, eval table, MIT.

## 7. Open owner decisions
1. Experts: local own-login `claude -p`/`codex exec` (policy gray zone) or API keys (spend, needs approval)?
2. Keep Archon after T2, or own the run table from day one?
3. Surface: chat CLI + Archon console first, or go straight to the ACP/Zed test?

## 8. Risks
NIM 503 and 27 s cold starts; subscription terms for automated use; Oracle capacity or reclaim; Archon is effectively maintainer-run (40 of 40 sampled merged PRs); several research cells are unverified (see `research/2026-11-12-findings.md`).
