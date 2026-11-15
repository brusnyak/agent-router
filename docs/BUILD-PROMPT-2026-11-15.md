# Build prompt v1 (2026-11-15)
Source: codex rewrite of the owner brief (28.8k tokens). Router rewrite (pi:NIM_1, 6 s) scored lower, see end.

Goal
Upgrade our agent router into a fast, lightweight execution system: deterministic routing plus proven capabilities selected from LiteLLM and Portkey, with a small original improvement that measurably improves execution. Support heavy lifting while minimizing token usage, API calls, and rate-limit pressure. Optimize quality, cost, and speed according to the task and model.

Constraints
- Inspect existing code, instructions, tests, and executor availability before changing anything.
- Reuse proven components after evaluating fit; avoid a minimal routing wrapper and indiscriminate feature copying.
- Keep every credential secret; reference configured credentials without printing or committing values.
- Enforcement must guide execution without a hard deny; preserve mandatory security and permission boundaries.
- Treat claims that jcode is faster than Claude Code, Hermes, OpenCode as hypotheses requiring comparable measurements.
- Preserve upstream provenance, versions, licenses, and required notices for anything placed in third_party or ported.
- Use bounded delegation and benchmarks; avoid recursive self-improvement loops and uncontrolled API usage.
- Define “actually perfect” as explicit acceptance checks agreed before implementation; do not claim universal perfection.
- Push to main only after the final acceptance checks pass and the complete change is reviewed.

Ordered steps and verifiable gates
1. Establish the baseline.
   Inspect architecture, existing capabilities, tests, configuration, and available execution paths. Record reproducible commands, current failures, and representative task results.
   Gate: a baseline report separates verified behavior, missing capabilities, and unknowns.

2. Improve and compare the build prompt.
   Use the agent router to parse this raw prompt into a better one; independently ask a codex model to do the same using identical input. Compare requirement coverage, ambiguity, feasibility, and verifiable gates.
   Gate: save both outputs, actual model identities, usage where available, and a scored comparison; retain every owner requirement.

3. Discuss essentials with a stronger model before implementation.
   Review the baseline, prompt comparison, architectural choices, tradeoffs, budget, and acceptance criteria. Have that model produce one consolidated build prompt for the local coding agent.
   Gate: save the discussion, decisions, unresolved questions, and final implementation prompt with a requirement-to-check mapping.

4. Gather resources and inspect upstream implementations.
   Take LiteLLM, Portkey and jcode apart into third_party using pinned, attributable source snapshots, subject to download authorization and licenses. Identify useful mechanisms and compare LiteLLM and Portkey against this router’s needs.
   Gate: produce a source-linked component matrix, select the best fit with evidence, and justify each proposed port and exclusion.

5. Design the execution upgrade and durable guidance.
   Specify routing, executor contracts, lightweight enforcement without a hard deny, usage controls, failure recovery, and task/model-specific quality-versus-speed policies. Add a dedicated skill or notion explaining the principle: take the best existing work, then add a measured original improvement.
   Gate: the design maps every change to a demonstrated need, source, acceptance check, and bounded resource cost.

6. Wire and verify executors.
   Integrate claude, codex, pi on NVIDIA API keys 1-3, and opencode, which the owner reports is installed locally, not running now. Verify actual availability and authentication without exposing credentials.
   Gate: each executor passes a bounded real-task smoke test; unavailable paths have exact blockers and are never reported as working.

7. Develop through the router itself.
   Use the agent router to delegate bounded tasks to antigravity through Orca, codex, opencode, cline, NVIDIA keys if needed. Log actual dispatch paths, outputs, failures, reviews, and resource usage.
   Gate: demonstrate real routed delegation and independent output verification; distinguish configured, attempted, and successfully executed paths.

8. Implement and measure selected improvements.
   Port the justified components incrementally and add the original improvement. Compare baseline and upgraded behavior on the same representative lightweight and heavy tasks.
   Gate: tests pass; measurements cover task quality, latency, token/API usage, failures, and limits. Retain improvements only with evidence or an explicit justified tradeoff.

9. Review, document, and release.
   Analyze mistakes, the biggest blocker, and how earlier reasoning and discussion could shorten future projects. Review the final diff, documentation, secret handling, licenses, and acceptance results.
   Gate: all agreed checks pass, required executor/delegation paths are demonstrated, and no blocking issues remain; then push to main and record the commit and push result.

Open questions
- Which stronger model should lead planning, and what API/token/spend budget applies?
- Which representative tasks and numerical quality, latency, and usage thresholds define acceptance?
- Does “dedicated skill or notion” mean a repository skill, a design document, or a Notion page?

## Rewrite comparison
- codex: 9 gated steps, push to main last, 3 open questions, jcode speed claim treated as hypothesis.
- router pi:NIM_1: ungated ("no gate"); step 1 gate says 'committed to main' (breaks push-last); caveman style dropped constraints.
- Router flaw found: without keys in env, run fails 'no NIM keys'; it should self-load via with-env.
