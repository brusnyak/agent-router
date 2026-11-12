# HANDOFF: Agent Router (2026-11-12, end of session). Read this, then `docs/VISION.md`.

Branch `dev/backbone`, nothing pushed. Repo: `~/Developer/agent-router`. Previous handoff: `docs/archive/HANDOFF-2026-11-12-backbone-history.md`. Reading order for docs: `docs/README.md`.

## 1. The thesis after today's research (this changes the plan)
The owner's pain is NOT "no executor plumbing". It is: (a) installed skills/commands/personas are almost never used unless named, and (b) dictated (Whisper) input is unstructured and gives weak results. Evidence:
- Own sessions (MEASURED, `~/.claude/projects`): 92 sessions / 953 prompts, Skill tool called 32 times (3%), 14 sessions (15%), 20 distinct skills; subagents in 74% of sessions.
- Vercel eval: skill by description 53% (= no skill), always-in-context index 100%; forced-eval hook 84-100% vs simple hook 20-59% (`docs/SKILL-ACTIVATION.md`, single-author, small n).
- The owner's existing `~/.agent-skills/router/router.py hook` is NOT wired in `~/.claude/settings.json` (0 matches).
So the first valuable product slice is a CONTEXT COMPILER delivered as a hook: for each prompt, structure the dictation, retrieve deterministically (vault/docs/library), pick the task class + bundle with a confidence gate, and INJECT a compact factual context via UserPromptSubmit `additionalContext` (Codex: AGENTS.md / exec wrapper). Execution/delegation (workers, hub/node, Oracle) is the second slice and already exists.

## 2. What exists (verified this session: `python3 -m pytest tests -q`; 2 legacy tests fail because they call the real NVIDIA API: tests/test_agent_base.py::test_nim_agent_dispatch_without_key, tests/test_supervisor.py::test_nim_key_available_flag)
- Backbone (39 modules in `backbone/`): key pool NIM_1..3, Pi/Claude/Codex/browser workers, LangGraph run graph + SQLite checkpoints (`runs resume`), jobs daemon, hub/node (`backbone node`, `@node:NAME`), serve HTTP + MCP, evidence check (`verified` only if cited paths exist; field `gate_passed`), vault privacy gate (`vault_to`).
- Library: 2,101 rows, 12 kinds (`python3 -m backbone library counts`), licence per row, dedupe module (not applied: 41 duplicate rows). Retrieval: hybrid BM25+NIM embeddings; NIM reasoning rerank top1 0.91 / top3 0.99 on 67 self-written kind-filtered queries (CONTAMINATED, see RESEARCH-AND-REDESIGN); no-LLM local hybrid 0.70/0.82 with kind, 0.49/0.66 without kind.
- Composer: `python3 -m backbone ask --dry "<raw>"` prints task class, persona, tier, engineered prompt, sources.
- Worker-built via the router, test-first, all gates passed attempt 1: `kind.py` (REJECTED by measurement: 0.31 LOO vs 0.36 baseline; do not wire), `dedupe.py`, `margin.py`, `outcomes.py`, `utility.py` (not wired); 6 bundles in `library/bundles/` (valid structure by `eval/check_bundle.py`; quality UNPROVEN, generic, not yet ingested).
- Telegram: router bot `router_lingonberry_bot` PAIRED (`python3 -m backbone telegram-pair`), outbound verified; inbound needs the daemon. A local `backbone daemon` is RUNNING (pid via `pgrep -f "backbone daemon"`): stop with `pkill -f "backbone daemon"` unless you want to test `/status` `/nodes` from the phone.
- Browser worker (Ego): `@browser Read <url> ...`, space always finished, no leaks verified.
- Held-out set: `eval/mine_transcripts.py` -> `eval/heldout/{dev,test}.jsonl` (949 real prompts, 190 frozen test by time, LOCAL, gitignored). Only 87 have a skill/agent label (8 in test): labels must come from owner spot-check and shadow-mode outcomes.
- Open-source gate: test fails on personal paths in tracked code; fresh-HOME `init` works.

## 3. Decisions made by the owner (do not re-ask)
- Standalone open-source project; Oracle is the always-on hub, the Mac is the dev machine; hub/node outbound-only.
- Clarification: retrieve FIRST (vault, project docs, library, earlier decisions); ask only what retrieval cannot answer, 3+ questions at once with a default each.
- Soul Knight test #1: the router researches idea-generation apps/trends to pick the THIRD PROJECT (fits the job technical requirements, viable for users/clients), then one-master-prompt build on it.
- Dependencies re-scoped by research (`docs/STACK.md`); NIM is a baseline, not a rule. Do not adopt hosted routers/Jev (user turn leaves the machine). Arch-Router rejected (licence).
- Spending on Claude/Codex allowed for the evals (one expert at a time); Neo on the owner's signed-in Kaggle allowed; BP/Kaggle only AFTER documentation/research of Kaggle requirements; do NOT touch `nearpitch`; nightcloser is `~/Documents/Acore/Development/nightcloser` (not a priority).

## 4. Next session: ordered plan with gates (stop at the first failed gate, write a ticket)
1 FIXTURE + SHADOW: build a 30-prompt should-fire / should-not-fire fixture from `eval/heldout` and the owner's catalog; run the context-compiler decision in SHADOW mode (log what it would inject, do not inject) over the 190 test prompts. Gate: decision logged with confidence for 100%; owner spot-checks 50.
2 HOOK v0 (`backbone/hook.py`, UserPromptSubmit, factual wording, <= 6k chars, score floor, silent on chit-chat): L0 rules + FTS5 + bge-small (onnxruntime, MIT) + margin gate. Gate: on the fixture, activation of the right bundle/skill >= +30 pp vs hook-off, <= 1 false positive of 15 negatives; p95 latency < 300 ms on the Mac.
3 TASK CLASS -> BUNDLE table: owner reviews/curates 10-15 real bundles (authored by workers, reviewed by Claude Haiku/Sonnet); measure bundle vs bare persona on held-out prompts.
4 DICTATION STRUCTURING step + retrieval-first clarification protocol (`docs/VISION.md` section 7).
5 M3 three-arm blind test (raw->Claude, raw->NIM, router->NIM) on the frozen test split. Kill rule: router must beat raw-NIM by >= 10 pp gate-pass (CI above 0) at <= 2x latency, else ship only deterministic parts.
6 Wire `outcomes` + `utility` into routing (replace the `tiers:` table); fix `verified` loopholes (basename match, `noop` gate); one retrieval per `ask`; apply `dedupe`.
7 Soul Knight test #1 (third-project research) using the router; then the master build prompt (`docs/COMPONENTS.md` section 6 structure).
8 Oracle: install onnxruntime/numpy there, re-sync, real Mac<->Oracle node test.
9 BP/Kaggle: first research what Kaggle expects (account, compute limits, model/DTS configs), write it down, only then dispatch.

## 5. First prompt for the next session (paste)
"Read HANDOFF.md and docs/VISION.md. Start with plan item 1 and 2: build the shadow-mode decision log and hook v0 per the gates. Use the router's own workers (`fanout`, test-first) for independent modules; keep integration yourself. No pushes, sends or spend beyond what HANDOFF.md section 3 allows."

## 6. Known weaknesses (do not hide them)
- The 0.91 retrieval number is contaminated (queries written by the building agent, kind given, best-of-five gate); trust only the held-out kind-less test.
- Worker-built modules pass their tests but a passing gate only proves the spec was met, not that the spec was right (kind.py).
- Bundles are structurally valid but generic; the gate cannot judge quality.
- Every research figure (`docs/SKILL-ACTIVATION.md`, `docs/STACK.md`) is from sources' own reports, small n, not reproduced; two are single-author.
- Router outputs were mis-routed repeatedly earlier (command picked by keyword); `ask` still makes ~6 LLM calls before work and retrieves twice.
- Hub/node and Telegram inbound are tested in-process only; Mac<->Oracle path unproven; Oracle VM not re-synced.
- `langgraph>=0.1.0` is pinned only by lower bound; pin before any build.
