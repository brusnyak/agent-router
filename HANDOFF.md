# HANDOFF: Agent Router (2026-11-13, end of day). Old handoff: `docs/archive/HANDOFF-2026-11-12-pre-shadow.md`

Repo `~/Developer/agent-router`, branch `dev/backbone`, private, nothing pushed. Oracle/Hermes: `docs/ORACLE-HERMES.md`.
Labels: proven = a command was run this session; reported = claim from a worker or the owner's brief, not re-run.

## (a) NEXT SESSION: paste this prompt
```
Read HANDOFF.md, then docs/MVP-2026-11-13.md and docs/INVARIANTS.md. Do not re-ask section (e).
Run `git status` and `python3 scripts/shadow_hook.py status` first; report both before changing anything.
Do the first unfinished step of section (d); stop at its first failed gate and write a ticket.
Use `.venv/bin/python` (absolute path in gates), run long tests in the background, never in the foreground.
Dev mode: show the owner the compiled prompt card. No pushes, sends, spend or settings.json edits without asking.
End with: what changed, the gate output, what is next. Keep it under 8 lines.
```

## (b) State in 10 lines
1. Exists: a shadow UserPromptSubmit hook, an outcome hook, a receipt/outcome log with treat-vs-holdout report, a dictation compiler, an offline librarian, a nightly script.
2. Modules (new, uncommitted, see `git status`): `backbone/{hook,hook_log,compile,health}.py`, `scripts/{shadow_hook,outcome_hook,nightly}`, `eval/{librarian,shadow_eval,shadow_enrich,spotcheck_cards,backfill_aa,build_catalog,...}`.
3. Merged: `kind.py` and its test deleted (staged, not committed). Everything else is on `dev/backbone`, not on main.
4. Silver labels (2 of 3 LLM judges agree): 517 of 1,011 real prompts, 124 in the frozen test split. Unverified by a human.
5. Retrieval vs silver: dense NIM embed top-1 25.0% / top-3 46.0%; always-guess floor 14.1%.
6. On the test split dense top-1 is 17.7%, below the always-"research" guess (25.8%).
7. Existing `~/.agent-skills/router/router.py` vs silver (proven, `eval/baseline_router.py`, first 300 chars): top-1 28.2%, top-3 42.6% (dev 31.6/47.3, test 17.7/27.4). Comparable to dense NIM, not better; test top-1 is below the always-guess floor.
8. Compiler (card as query vs raw first 300 chars, `eval/compile_test.py`, proven): top-3 50.1% vs 48.9% (+1.2 pp, below the 5 pp bar; test split +5.7 on n=124 is noise). Ship as structure only, no retrieval claim. Partly circular (silver was judged from raw text). Embedding only the first 300 chars beats the full prompt (28.4/48.9 vs 25.0/46.0).
9. A/A replay (`backbone aa-replay`, proven): treat 599 prompts 1.7% followed, holdout 386 at 1.6%, diff 0.1 pp, p=0.89, "A/A OK". The measurement pipeline is sound; today's baseline agreement is 1.7%.
10. Tests: last full run 171 passed, 0 failed (102 s, before the invariants, named-things, A/A and CLI patches were added; their own gates pass). The two legacy NVIDIA-API tests are now hermetic. Run the suite in the background.

## (c) What is wired and what is not
- Shadow hook: `scripts/shadow_hook.py install` writes `UserPromptSubmit -> backbone/hook.py` into `~/.claude/settings.json`. It logs a receipt (hash, length, ids; never prompt text) and prints nothing. Registered by the owner on 2026-11-13 19:12 (proven: `status` returned owned_entries 2; backup `settings.json.bak-20261113-191236-shadowhook`). Cold start 30 ms p50 / 33 ms p95 with `/opt/homebrew/bin/python3` (system python 80 ms, pyenv shim 97 ms). Orca may rewrite settings.json hooks: re-run `status`.
- Outcome hook: same installer adds `PostToolUse` matcher `Skill|Agent|Task -> scripts/outcome_hook.py`. It writes outcome rows used by `python3 -m backbone.hook_log report`.
- Uninstall (removes only our entries, writes a timestamped backup first):
  `python3 scripts/shadow_hook.py uninstall` (preview with `--dry-run`). Backups sit next to settings.json as `settings.json.bak-*-shadowhook`.
- Receipts: `~/.agent-router/hook-shadow.jsonl`; enriched: `~/.agent-router/hook-shadow-enriched.jsonl`.
- NOT wired: nothing injects into any session. `rag.py`, `margin.py`, `outcomes.py`, `utility.py`, `dedupe.py` are not in the hot path. `~/.agent-skills/router/router.py hook` and `intake_hook.py` are not registered (reported: 0 matches in settings.json).
- NOT wired: Oracle re-sync, Telegram inbound, Mac<->Oracle node test, nightly cron/launchd (`scripts/nightly.sh` exists, nothing schedules it).

## (d) Next steps in order, with gates (from `docs/MVP-2026-11-13.md` and `docs/ROADMAP-2026-11-13.md` section 8; stop at the first failed gate)
1. Owner spot-check. Generate cards with `eval/spotcheck_cards.py` (the old `spotcheck.md` sheet was unreviewable). Gate: >= 70% of the checked silver items OK, lower Wilson bound >= 0.7; else relabel with a stronger judge before tuning.
2. Finish A/A (`eval/backfill_aa.py`) and let the shadow run collect receipts (2 weeks). Gate: A/A OK, receipts for 100% of prompts.
3. Routing bar (dev only, test split run once): shortlist top-3 >= 46% on silver dev; where the gate fires, label inside the shown 3 at >= 60% precision with >= 25% coverage. Else ship shadow only and say so.
4. Prompting bar: compiled query beats raw by >= 5 pp top-3, 100% of named entities verbatim in the card, and blind owner preference 8 of 10 cards.
5. Latency: 20 cold runs of FTS5-only `hook.py`, p95 < 300 ms. Fail open always.
6. Delegation bar: `backbone ask --dry "<dictation>"` gives class, tier and gated packet for 10 of 10 hand-picked prompts; one real worker run passes the evidence gate and writes an outcome row.
7. Librarian bar: 73 of 73 scored, deterministic across 2 runs, 44 never-invoked flagged "review", nothing moved without owner approval.
8. Only then: live injection behind a 20% holdout; metric = Skill-tool calls per prompt (baseline 3%). Then the three-arm blind test (router must beat raw-NIM by >= 10 pp, CI above 0, at <= 2x latency, else ship the deterministic parts only).
Scope fence: <= 5 new modules < 300 lines each, <= 1000 new non-test lines (hard cap 1200), size ratchet in `docs/complexity-budget.json`. Not built: embedder in the hook, semantic-router, auto-install, auto-archive, UI, Rust/Go.

## (e) Decisions already made by the owner (do not re-ask)
- Repo stays private until hook v0 has a measured result. Python + LangGraph stack; no Rust/Go rewrite.
- Librarian proposes only; archive is reversible; nothing moves without owner approval.
- The first spot-check sheet was unreviewable; use `eval/spotcheck_cards.py` cards instead.
- `kind.py` rejected by measurement (0.31 vs 0.36) and deleted.
- Compiled prompt is shown to the owner in dev mode before anything depends on it.
- Standalone open-source project; Oracle is the always-on hub, Mac is the dev machine; hub/node outbound-only.
- Retrieve first, ask only what retrieval cannot answer. Do not adopt hosted routers (user turn would leave the machine). Do not touch `nearpitch`.

## (f) Known weaknesses and traps
- Isolated router workspaces see only committed files. For tasks that depend on uncommitted work pass `--no-isolate`.
- Codex worker is unusable (60 s timeout). Pass `--escalate ''` so no escalation to it is attempted.
- Gates need absolute python paths (`/Users/yegor/Developer/agent-router/.venv/bin/python`), not `python`.
- Never wait on a long test in the foreground; run it in the background and poll.
- Silver labels are LLM-made and unverified. Judge agreement ~47% overall, 29% on prompts over 2,000 chars (the dictation case). Treat silver as a dev tool.
- 310 of 1,321 mined prompts were relayed subagent messages, not owner prompts (the miner now drops them; 1,011 remain). Old files under `eval/heldout/` still contain them.
- Real invoked labels are only 80 of 1,011; they are habit, not truth (silver agrees with 11 of 80).
- NIM embed returns 500 for batches > 1. NIM calls need `~/.claude/scripts/with-env NIM_1 NIM_2 NIM_3 -- <cmd>`; never print key values.
- Several research numbers are worker-reported (`research/2026-11-13-*.md`); stars/dates were spot-checked on 3 items, one error found.
- langgraph and friends are now pinned exactly in `requirements.txt` (from the working `.venv`); `langgraph-checkpoint-sqlite` had been missing from the venv, which made `backbone` fail to start. Fixed 2026-11-13.
- `backbone compile --no-llm` extracts overlapping fragments of the same path or URL (`~/x/y.py`, `x/y.py`, `y.py`, `a.b`): nothing is lost but the Named list is noisy. Fix: keep only the longest non-overlapping match. A `backbone run` worker may skip unusable workers via `backbone/health.py` (data/doctor.json); run `backbone doctor` first.
- The worker-isolation trap above also hit three builds that produced empty patches; `--no-isolate --escalate ''` fixed all three.
- Hub/node and Telegram inbound are tested in-process only; Oracle not re-synced.

## (g) 8 commands to see it work (each exists in `backbone/cli.py` or the file's argparse; run from the repo root)
1. `.venv/bin/python -m backbone ask --dry "fix the failing test in the router"` (prints class, persona, tier, prompt, sources; runs nothing)
2. `.venv/bin/python -m backbone library counts`
3. `.venv/bin/python -m backbone router-report` (add `--json`; treat-vs-holdout from live receipts)
4. `.venv/bin/python -m backbone librarian` (propose-only report to `research/`; nothing is moved)
5. `.venv/bin/python eval/shadow_eval.py --source embed --split dev` (offline margin-gate replay, no network)
6. `.venv/bin/python -m backbone enrich --dry-run` (fill `would_surface` on receipts; real run needs NIM keys via with-env). Also: `backbone aa-replay`, `backbone compile --no-llm "<text>"`.
7. `python3 scripts/shadow_hook.py status`
8. `NIGHTLY_DRY=1 sh scripts/nightly.sh` (prints the 4 nightly steps, runs nothing)
Tests: `.venv/bin/python -m pytest tests -q -k "hook or compile or librarian or invariants"` (run in the background).
