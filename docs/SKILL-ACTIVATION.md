# Making agents actually use skills: evidence and implications (2026-11-12)

Source: researcher agent, 9 primary sources read via WebFetch; numbers are single-author, small-n, not independently reproduced unless stated. Local measurement is mine.

## Owner's own data (transcripts, `~/.claude/projects`, read-only)
92 sessions with >= 2 human prompts, 953 prompts: Skill tool called 32 times (3% of prompts) in 14 sessions (15%), 20 distinct skills. Subagents spawned in 68 sessions (74%), 421 calls, 23 types (researcher 108, roast 61, general-purpose 42, engineer 37, copywriter 34, skeptic 30). Caveat: cannot separate explicit requests from spontaneous use; this session's own agent calls are included. Reading: the owner uses agents he named; installed skills are almost never chosen by the model.
The owner's `~/.agent-skills/router/router.py hook` (UserPromptSubmit) exists but `~/.claude/settings.json` has no router entry (grep: 0 matches): the existing router is not wired into Claude Code.

## Evidence
| Mechanism | Result | Source |
|---|---|---|
| Skill with description only (default) | 53% = same as no skill; "in 56% of eval cases the skill was never invoked" | Vercel eval, https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals |
| Skill + explicit instruction | 79% | same |
| AGENTS.md docs index always in context (~8 KB compressed) | 100% ("no decision point") | same |
| Simple one-line hook | 20% (10/50, Haiku 4.5 synthetic) ; 55-59% in real `claude -p` sandbox | https://scottspence.com/posts/how-to-make-claude-code-skills-activate-reliably ; .../measuring-claude-code-skill-activation-with-sandboxed-evals |
| Forced-evaluation hook | 84% synthetic (42/50); 100% on 22 prompts x2 (Sonnet 4.5); on a harder set 75% with 0 false positives on 5 negatives | same |
| Small-model pre-classify then inject | 100% easy set, 4 false positives on 5 negatives | same |
| Tool search (Anthropic) | tool-choice degrades past ~30-50 tools; claims >85% token reduction (unquantified accuracy) | https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool |
| Skill retrieval at scale (SkillRouter) | 74% Hit@1 over ~80K skills with body-aware retrieve+rerank; hiding the body costs 37-44 pp | https://arxiv.org/abs/2603.22455 |
| Prompt format sensitivity | formatting alone swings accuracy up to 76 points (old open model) | https://arxiv.org/abs/2310.11324 |
| Many instructions at once | best frontier model 68% at 500 instructions; earlier ones favoured | https://arxiv.org/abs/2507.11538 |

Platform facts (Claude Code docs): skill descriptions are always in context (cap 1,536 chars each); UserPromptSubmit `additionalContext` is injected at the turn, cap 10,000 chars per hook output; write injected text as factual statements, not imperatives; a Stop hook with exit code 2 sends the model back to work; a PreToolUse timeout does not block. Codex: skills chosen implicitly by description within a 2%-of-context list budget; AGENTS.md loaded once per run, 32 KiB cap.

## What this means for the router (ranked by expected effect)
1. DETERMINISTIC PRE-INJECTION: the router selects the bundle/skill and a hook injects its body (or head + path) via UserPromptSubmit `additionalContext`, with a score floor so chit-chat gets nothing. Highest measured effect (100% vs ~53%).
2. Always-on compact index (name + one-line trigger + path, ~8 KB, grouped) in CLAUDE.md/AGENTS.md: removes the decision point; keep it short.
3. Forced explicit selection step, factual wording: 84-100% in small tests; needs the owner's own negative examples.
4. Descriptions that front-load the use case; `disable-model-invocation` for side-effect skills.
5. Stop hook that exits 2 until a named acceptance check ran (enforces verification, not selection; needs a loop guard).
6. LLM pre-classifier before injection: lowest rank (extra call, false positives).
Build the cheapest test first: a 30-prompt fixture (15 should-fire, 15 should-not-fire) for the owner's catalog; run hook off and on; count Skill tool calls from transcripts.

## Unknowns
Own-catalog precision/recall; Cursor/Cline/OpenCode/Gemini behaviour; whether bodies vs descriptions matter at ~50-500 assets; the cited 84% and 56% figures rest on one author each.
