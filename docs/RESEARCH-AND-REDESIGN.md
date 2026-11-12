# Research + roast synthesis and redesign (2026-11-12)

Inputs: roast agent (static review, no shell), researcher agent (web, abstract-level numbers), my measurements. Every research number below is from abstracts or secondary summaries unless marked; open the paper tables before quoting.

## 1. What the owner said, checked
| Claim | Verdict | Evidence |
|---|---|---|
| System cannot rely on LLM reasoning alone | CONFIRMED | one `ask` = ~6 NIM calls before any work (analyze, expand, rerank, decide, then expand+rerank again in resolve); nothing deterministic gates them (core.py ask/retrieve/resolve) |
| Library is bulk, not researched | PARTLY | 2,101 rows; ECC is 28% (580), Piebald Claude Code internals 29% (603), anthropics plugins 6%; 28 duplicate (kind,name) groups = 41 extra rows (e.g. `DESIGN` x10, `code-reviewer` x4); no quality column (db.py); body lengths: hook avg 737 chars, system 1.6k |
| No routing math | CONFIRMED | `tiers:` is a hand table; latency_ms recorded and never read; experts are opt-in so review/plan/multi_file tiers silently fall back to nim1 |
| No extra reasoning | CONFIRMED | only the gate loop (spec, spec, expert); critic maps "fail with no quoted issue" to pass, needs OpenRouter key |
| No concrete memory across a session | CONFIRMED | `ask()` passes no session so every ask opens a fresh uuid; turn is added before pack so recall returns it twice; recall is BM25 only |
| Hook/loop corpora missing | CONFIRMED | hooks = Claude Code reminders; loops = 3 appendix docs |
| Measurement shows router alone is not enough | CONFIRMED | replay 24/24 both arms (katas, ceiling); L3 A/B router 19 min vs Claude 4 min with fabricated output; M3 blind test not done |

## 2. Faults the owner did not name (roast)
- Eval contamination: 5 `application` + 3 `loop` queries target files the agent itself wrote; design queries contain the target's name; zero queries for hook/prompt/clip; zero kind-less; queries whose target is missing are dropped; gate passes on the best of 5 methods; n=67 => about +/-7pp. Headline 0.91 is NOT evidence of routing value.
- Privacy: vault notes were pasted into every packed prompt, including to free API tiers. FIXED today: vault only to workers in `vault_to: [claude, codex]` (graph.py).
- `verified` loopholes: basename match accepts a fake path; the `noop` gate yields verified=true.
- `ask` retrieves a second time on the persona text, not the user's request.

## 3. Research (what exists, what is cheap enough to build)
- Replay/held-out eval from the owner's real history is the prerequisite for every other claim (no source needed).
- Contextual retrieval (Anthropic): prepend an LLM-written one-line context to each asset at INDEX time; reported failure rate 5.7% -> 2.9% (BM25+embeddings), 1.9% with rerank (secondary summary). Costs one call per asset once, nothing per query.
- SkillRouter (arXiv 2603.22455, preprint): hiding skill BODY drops routing accuracy 37-44 pp; index the body. 74% Hit@1 over ~80K skills.
- Routing: RouteLLM (arXiv 2406.18665) reports >2x cost cut at quality parity (model routing, not agent routing); FrugalGPT cascade (arXiv 2305.05176): cheap first, accept if scorer >= tau, else escalate; needs labels. Bandit/Thompson only after ~200 labelled outcomes.
- Scoring rule (a design, not a sourced result): `score(route, class) = p_accept(route, class) - lam*cost - mu*latency`, `p_accept` = Beta posterior from logged outcomes; "most accurate" lam=mu=0; "fastest" = hard floor p_accept >= 0.7 then minimise latency; drop Pareto-dominated routes first; free routes carry a quota penalty (OpenRouter free: 20 RPM, 50/day under 10 credits, 1000/day at 10+, account-wide: verified from the docs by the researcher; NIM limit unverified).
- Extra reasoning: deterministic verifiers first (gate, schema, evidence); self-consistency N=3 only for short checkable answers (arXiv 2203.11171: +17.9 on GSM8K with PaLM-540B); Reflexion only where tests exist; Chain-of-Verification is 3-4x calls, too costly on free-tier RPM.
- Memory: mem0/Zep/A-MEM numbers conflict across summaries by 5-10 points and one independent A/B found no gain over strong RAG: build the minimal SQLite design (turns, facts with validity window, pinned facts, FTS + vector, fold older turns) and evaluate on the owner's own sessions.
- Prompt optimisation (DSPy, OPRO, TextGrad): needs a metric and labelled set; defer until the outcome log exists.
- Local note the router work ignored: `~/memory-vault/pages/research/router-landscape-2026-10-31.md`.

## 4. Redesign (what changes in the spec)
1. Outcome log: every run writes (task_class, route, gate_pass, evidence_ok, latency, tokens, owner accept/reject). Substrate for math, curation and eval.
2. Held-out replay set: 100 REAL prompts (from `~/.claude/projects` transcripts and the runs table), kind-less, frozen BEFORE any tuning, with labels = what the owner actually used/accepted; report CI; run NIM-alone vs router vs Claude blind (M3).
3. Retrieval v2: index the body + a contextual one-liner per asset; dedupe by (kind,name) and embedding cosine > 0.9; LLM expand/rerank only when the deterministic top-1/top-2 margin is small; abstain to raw passthrough below a calibrated score; one retrieval per ask, cached.
4. Routing v2: replace `tiers:` with the utility score above; epsilon-explore; quota-aware for free routes.
5. Reasoning v2: verifier cascade (deterministic checks, then one extra pass); critic never fails open; self-consistency opt-in per task class.
6. Memory v2: default session per project; turn added AFTER pack; facts table with pinned + validity; hybrid recall; a dedicated session-memory skill + hook pair authored and measured.
7. Library v2: author 10-15 command+hook+loop+persona+skill BUNDLES for the owner's real task classes (review, research, gated build, lead-gen/ICP, CV/job research, product review), each with a gate and a version; bulk ECC/Piebald rows become a lower-prior reference tier; per-asset win-rate from the outcome log.
8. Fix `verified` (full relative path match; noop gate never verified).

## 5. Build order with gates
A. Outcome log + held-out set + M3 kill test (gate: router-composed beats NIM-alone on gate-pass by >= 10pp with CI above 0 at <= 2x latency; else ship only the deterministic parts).
B. Retrieval v2 + dedupe + one-retrieval-per-ask (gate: held-out kind-less top-3, with CI, beats the current pipeline).
C. Routing utility + quota awareness (gate: lower cost at equal gate-pass on the replay log).
D. Memory v2 (gate: 30 known-answer questions over owner sessions; tokens injected per turn).
E. Bundles (gate: each bundle beats the bare persona on the held-out set).
