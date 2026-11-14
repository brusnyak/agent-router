# Enforcement experiment (plan, 2026-11-14; nothing implemented)

## Gap
`backbone/hook.py` is shadow-only: it injects one generic heavy-task nudge in the treat arm and never names a skill. The A/A replay (1.7% vs 1.6%, p=0.89) therefore says nothing about enforcement. The product thesis (force skill use, delegate to different models) is untested.

## Thesis
Skills are ignored because they are only advertised. Indexing them beforehand and enforcing use through hooks raises the Skill/Agent call rate, without lowering the result quality.

## Arms (hash of session id, 4-way split)
- A holdout: nothing.
- B advice: top-3 skills listed in additionalContext.
- C require: top-1 skill injected as an instruction ("invoke Skill X first").
- D enforce: C plus a Stop hook that blocks once, "skill X not used", if the score of the top-1 is above a threshold.

## Metric
Primary: follow rate = a Skill/Agent call in the same prompt turn (PostToolUse outcome hook, already logged). Guard: owner-labelled success on a held-out sample; tokens and turns per task. Report pp difference with CI per arm vs A.

## Delegation (second claim)
Per task class, executor chosen by a measured table (accuracy on gate, cost, latency, quota). Claim only what `eval/` shows for at least 2 different models on the same gate.

## Rules
Failing test first for every hook change. Offline index from the library (no LLM or network in the hook, 0.3 s deadline stays). A/B must stay measurable: no change to the holdout arm. Nothing is pushed.

## Open
Skill index source (library vs `~/.claude/skills`); threshold for D; whether Stop-hook blocking is allowed by the harness for the target agents (check per agent: Claude Code, Codex, OpenCode, Hermes). Nina mission 7 survey feeds the cherry-pick list.
