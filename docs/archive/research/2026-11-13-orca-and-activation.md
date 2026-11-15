# Orca + skill activation research (2026-11-13)

Scope: 2 sub-tasks. Browser: ego-browser, read-only, 6 of 6 pages read (see S1). Local: `orca` CLI help (read-only).
Labels: proven (URL + quote) | assumed | unknown | unverified.

## Sub-task 1: skill activation via hooks

Pages read: 6 of 6 (Vercel blog; scottspence Nov 2025; scottspence sandbox Feb 2026; code.claude.com hooks; code.claude.com skills; code.claude.com settings). Hooks and settings pages were keyword-grepped, not read whole.

| # | Claim | Source | Quoted line | Verified? |
|---|---|---|---|---|
| 1 | Skill with default description: 53%, same as no skill | https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals | "Skill (default behavior)" 53%; "Zero improvement." | proven. Next.js 16 docs eval, not a hook. Page date: unverified (none in page text) |
| 2 | Skill never invoked in 56% of cases | same | "In 56% of eval cases, the skill was never invoked." | proven |
| 3 | Explicit "MUST invoke" in AGENTS.md: 79% | same | "skills maxed out at 79% even with explicit instructions" | proven |
| 4 | Compressed 8KB docs index in AGENTS.md: 100% | same | "A compressed 8KB docs index embedded directly in AGENTS.md achieved a 100% pass rate" | proven |
| 5 | "Forced eval hook 84-100%" is a VERCEL result | Vercel page | no mention of forced eval, hook, or UserPromptSubmit in page text | REFUTED attribution. HANDOFF sec 1 misattributes. The 84/100 figures come from scottspence (rows 6-9). Vercel's "84%" is a per-category Build score, not a hook |
| 6 | Forced eval 84% (42/50), Haiku 4.5, synthetic API | https://scottspence.com/posts/how-to-make-claude-code-skills-activate-reliably | "Forced \| 84% (42/50)"; "The results below came from synthetic API calls." | proven, synthetic, single author. Post dated NOVEMBER 16, 2025 |
| 7 | Same post's own update says follow-up results differ | same | "Update, 13 September 2026: ... The setup and results differ, so read those before treating these percentages as a prediction" | proven. Use the Feb 2026 numbers instead |
| 8 | Simple one-line hook 20% (10/50), synthetic | same | "Simple \| 20% (10/50)" | proven, synthetic |
| 9 | Forced eval 100% (22/22) and llm-eval 100% (22/22), real `claude -p` in Daytona sandbox, Sonnet 4.5 | https://scottspence.com/posts/measuring-claude-code-skill-activation-with-sandboxed-evals (FEBRUARY 8, 2026) | "forced-eval \| 100% (22/22) \| 100% (22/22)" | proven 2026 reproduction, but same author, n=22, 2 runs only |
| 10 | Simple hook 59% run 1, 50% run 2 (sandbox) | same | "simple \| 59% (13/22)"; run 2 "50% (11/22)" | proven. HANDOFF "20-59%" mixes synthetic 20% with sandbox 59% |
| 11 | No hook baseline 55% / 50% (sandbox) | same | "none (control) \| 55% (12/22)"; "50% (11/22)" | proven |
| 12 | Native `type: "prompt"` hook: no gain (55% / 41%) | same | "type-prompt doesn't help"; run 2 "41% (9/22)" | proven. Not in HANDOFF; new |
| 13 | Harder set, 24 prompts incl 5 no-skill: forced 75% (18/24), 0 false positives; llm-eval 67%, 4 false positives | same | "Overall accuracy 75% (18/24)"; "False positives 0"; "llm-eval hallucinated on the non-Svelte queries" | proven, n=24, single author |
| 14 | additionalContext cap 10,000 chars (also systemMessage, initialUserMessage, plain stdout) | https://code.claude.com/docs/en/hooks | "A hook's additionalContext, systemMessage, and initialUserMessage strings, and its plain stdout, are capped at 10,000 characters" | proven |
| 15 | Over cap: saved to file, 2,000-char preview, Claude not asked to read it | same | "Claude Code doesn't ask Claude to read the file, so keep anything Claude must always see within the cap." | proven. Implication: keep injected text under 10k |
| 16 | Skill listing: description + when_to_use truncated at 1,536 chars per skill | https://code.claude.com/docs/en/skills | "truncated at 1,536 characters in the skill listing" | proven (per skill) |
| 17 | Total skill listing budget (2% of context) for Claude | skills page | not found in page text | unverified. "2%" in HANDOFF is for Codex, not read this session |
| 18 | skillOverrides: absent = "on"; `"off"` hides; `"user-invocable-only"` option | https://code.claude.com/docs/en/skills | "A skill that is absent from skillOverrides is treated as \"on\"."; "set one skill to \"off\" in skillOverrides to hide it" | proven. Settings page text: no skillOverrides match in grep, so the key is documented on the skills page only |
| 19 | Frontmatter `disable-model-invocation: true` removes skill from Claude context | https://code.claude.com/docs/en/skills | "Hide individual skills by adding disable-model-invocation: true to their frontmatter. This removes the skill from Claude's context entirely." | proven |
| 20 | Stop/SubagentStop exit 2 sends Claude back to work | https://code.claude.com/docs/en/hooks | "exit code 2 on these events sends Claude back to keep working" | proven |
| 21 | PreToolUse timeout does not block | hooks page | not checked | unverified |
| 22 | Skill re-attach after compaction: 5,000 tokens each, 25,000 combined | https://code.claude.com/docs/en/skills | "keeping the first 5,000 tokens of each. Re-attached skills share a combined budget of 25,000 tokens." | proven |
| 23 | Skill-hook limit 1,024 hooks per source, matchers 16,384 chars | hooks page | "The skills from one source can register at most 1,024 hooks." | proven |
| 24 | Codex skill list 2%-of-context budget; AGENTS.md 32 KiB cap | none read | none | unverified |

Read of activation evidence (proven rows only):
- Explicit deterministic injection or forced evaluation beat the simple one-line hook in both harnesses (synthetic 84% vs 20%; sandbox 100% vs 50-59%). Both authors are single-author, n=22 to 50.
- Forced eval had 0 false positives on no-skill prompts (row 13); llm pre-classify had 4. This matters for the router's negative cases.
- Vercel's strongest result is passive docs index (100%), not hooks. Different eval (Next.js 16 APIs), not replicated.
- No independent 2026 reproduction found. Only the same author's follow-up (row 9).

Unknowns: Vercel post date; Claude total listing budget; whether hook output is weighted lower than system reminders (author guesses this for type-prompt, row 12; assumed).

## Sub-task 2: Orca orchestration surface

Local help run (read-only): `/Applications/Orca.app/Contents/Resources/bin/orca --help` and `orca orchestration --help` and `orca orchestration <cmd> --help` for run-create, task-create, worker-start, worker-show, worker-read, worker-stop, worker-release, dispatch, ask, reply, check, task-update, gate-create. Bundled guide read via `orca skills get orchestration` (+ references coordinator-loop, messaging-and-gates, recovery-and-cleanup). Saved under scratchpad.

Quoted local help (proven):
- Top-level: `orchestration worker-start Start a supervised worker locally or on a connected Orca server`
- `orca orchestration worker-start` usage: `(--task <task_id> | --spec <text> | --spec-file <path|->) [--keep-open] ... (--agent <agent> | --terminal <handle>) ...`
- `--agent takes an Orca agent id enabled on the worker server, such as claude, codex, cursor, ...`
- `Finished workers close on their own unless started with --keep-open; a worker started in a new worktree (new-child or new-top-level) is kept open`
- `orca orchestration ask`: `--timeout-ms ... (default 600000 = 10 minutes, max 30 minutes)`
- `orca orchestration check`: `--wait: block until a matching message arrives or --timeout-ms expires. Emits JSON keepalive lines to stderr every 15s`
- `orca orchestration task-update`: `Valid --status values: pending, ready, dispatched, completed, failed, blocked.`
- `orca orchestration run-create`: `A Run is a namespace and home inbox. It never schedules or places workers.`
- `orca orchestration worker-read`: `Output stays readable after the terminal is released, including an automatic release after worker_done.`

Bundled guide (proven, `orca skills get orchestration`): `"ORCA orchestration worker-start --spec "<task>" --worktree current --agent codex"`; `Start every independent worker, then **end your turn**.`; `Never: Poll or run watch scripts: a script's plain check takes your mail`.

Limits (proven from local guide): `After three failed starts in one --retry-of chain, the Dispatch circuit-breaks and the Task fails.` (recovery-and-cleanup). `Workers editing the same files at once need separate workspaces.` (coordinator-loop). Auto-release ~2 min after `worker_done` on runtimes advertising the capability (worker-release help).

Public docs read (2 of 2 official pages, via ego-browser, 1 search page; tabs closed):
- https://www.onorca.dev/docs/cli/orchestration: "Orchestration is Orca's structured multi-agent layer: a Run (namespace + coordinator inbox), Tasks, Dispatches, supervised workers, messages, and decision gates." proven.
- same: "Workers can start helper workers up to the Nested worker depth in Settings. The default is 4" proven.
- same: "Under Settings → Agent Orchestration, turn worker heartbeats off or choose an interval from 1 to 60 minutes. The default is 5 minutes." proven.
- same: "worker_done requires --outcome succeeded|failed." proven.
- same: "--effort requires --model and only applies when that agent/model supports the level." proven.
- same: "orca orchestration run and run-stop (and coordinator-start / coordinator-stop) perform no effects." proven. Do not use these.
- https://github.com/stablyai/orca/blob/main/skill-guides/orchestration.md: same recipe as bundled guide (`worker-start --spec ... --agent <agent>`, "end your turn", "Never: Poll or run watch scripts"). proven. Matches the local binary guide.
- Repo confirmed as stablyai/orca (search result; not separately opened).
Orca version: unknown (not printed by binary).

Minimal call sequence (every command below appears in local --help output):

```text
ORCA=/Applications/Orca.app/Contents/Resources/bin/orca
$ORCA status --json                                   # runtime up? (orca open if not)
$ORCA orchestration run-create --objective "<goal>"   # Run namespace; required for Tasks
$ORCA orchestration task-create --spec-file - --task-title "codex review" < codex-packet.md   # returns task id
$ORCA orchestration worker-start --task <codex_task> --worktree current --agent codex --json
$ORCA orchestration worker-start --spec-file - --worktree current --agent claude --json < claude-packet.md
# end turn: Orca wakes the coordinator with worker_done mail; do NOT poll
$ORCA orchestration check --peek --json               # read mail without consuming (or plain check to consume)
$ORCA orchestration worker-show --dispatch <dispatch_id> --json
$ORCA orchestration worker-read --dispatch <dispatch_id> --source auto --json   # result output
```

Notes for the router: use `--spec-file -` to avoid shell quoting; use `--keep-open` only if the user will watch the chat; `check --peek` for a script, never plain `check` (it takes the coordinator's mail).

Caveat: the `--worktree current` placement is what the bundled guide shows; not tested by running a worker (no spend, no launch in this session).

## Unknowns
- Public Orca docs/repo and version: unknown (not read).
- Whether `--json` output has a stable `dispatch_id` field: assumed from help text, not run.
- Remote/SSH placement: not read (references/placement-and-remote.md not fetched).
