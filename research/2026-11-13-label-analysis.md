# Label analysis 2026-11-13 (no prompt text quoted)
Scripts (python3 -I, scratchpad): /private/tmp/claude-501/-Users-yegor/29ec7af2-e94e-4fdf-aa0b-43592f8d2332/scratchpad/s/t1.py, t2.py

## Sub-task 1: judge agreement (1011 real prompts; relayed excluded)
- Sonnet-NIM n=1011: agree 41.1%, kappa 0.326.
- Sonnet-Haiku n=595: agree 42.2%, kappa 0.382. CAVEAT: the 595 Haiku-judged are the Sonnet-NIM disagreements (3-way all-agree = 0 of 595 by construction), so this is a selected, hard subset, not a random sample. Do not compare kappas directly.
- None-rate: Sonnet 28.7%, NIM 37.7%, Haiku 11.4% (Haiku rarely abstains: it forces a label).
- Agreement by length (Sonnet-NIM / Sonnet-Haiku): <200: 66.5% (n206) / 60.9% (n69); 200-599: 39.6% (265) / 43.8% (160); 600-1999: 32.6% (482) / 38.5% (325); >=2000: 29.3% (58) / 34.1% (41).
- By prior prompts in session: 0: 53.1% (245) / 49.6% (115); 1-3: 36.5% (233) / 39.9% (148); 4+: 37.7% (533) / 40.7% (332).
- By truncated: S-N true 58.4% (113) vs false 39.0% (898); S-H true 29.8% (47) vs false 43.2% (548). Truncated is NOT a consistent signal (S-N higher, likely because truncated ones are long pastes both call none).
- By split: S-N dev 42.4% (768), test 37.0% (243); S-H dev 41.0% (442), test 45.8% (153).
- Top confusions S-N (Sonnet label, NIM label): engineer/none 67, engineer/research 19, engineer/roast 13, none/roast 13, engineer/executing-plans 12, none/research 12, none/retro 11, none/executing-plans 11, vault-memory/none 10, research/none 10.
- Top confusions S-H (Sonnet, Haiku): engineer/orchestration 13, engineer/none 12, none/research 12, engineer/research 12, lead-generation/lead-dossier 8, engineer/vault-memory 6, none/engineer 6, none/vault-memory 6, delegation-and-batch/orchestration 6, brainstorming/engineer 5.
- Per-label agreement (S-N, rate of items either judge gave L that both gave L): none 41% (476), roast 25% (140), research 30% (138), engineer 1% (126; NIM almost never emits engineer, systematic), market-discovery 10% (50), lead-generation 19% (48), vault-memory 34% (47), executing-plans 2% (43), browseros-neo 37% (35), impeccable 33% (33), skill-router 20%, devcoach 20%, delegation-and-batch 13%, orchestration 4%.
- Highest-agreement labels are few and still only ~1/3 (browseros-neo, vault-memory, impeccable). Near-synonym pairs dominate low agreement: lead-generation/lead-dossier, delegation-and-batch/orchestration, engineer/orchestration.
- Judge disagreement is mostly engineer vs none and generic-agent confusion, i.e. a taxonomy overlap problem, not only noise.

## Sub-task 2: gating + dictation rules
Scripts: scratchpad/s/t2.py (gating, lexical), scratchpad/s/t3.py (agreement-gates, text-reduction). Silver = 517 of 1011 real (51.1%).

Dense recompute: NOT possible. eval/baseline_embed.py keeps only aggregate counts; no per-prompt vectors or per-prompt ranks are saved anywhere (searched the repo), and re-running needs NIM network. So the 46% top-3 cannot be re-split by subset. Offline lexical version (eval/baseline_retrieval.py logic, copied in t2.py): all silver top-1 11.4%, top-3 21.1% (matches ROADMAP 21.1%).

What predicts "abstain" (silver absent = no 2-of-3 non-none label), weak signals only:
- Silver-rate by length: 60-199 chars 38.7% (lowest), 30-59 53.7%, 200-599 52.5%, 600-1999 53.9%, >=2000 55.2%. <200 overall 41.7% (n206).
- lines>=30: silver-rate 35.1% (n37, 3.7%) vs 51.7% rest. But judge agreement on these is high (68.6%), i.e. judges agree it is none.
- truncated 46.0% vs 51.8%; prior 0 57.6% vs prior 4+ 48.8%; fence/URL/traceback: no abstain signal (higher silver rate, tiny n).
- Verdict: surface features do not separate labelable from unlabelable. No cheap rule reaches even 10 points of silver-rate difference at useful coverage. Treat abstain as a model decision, not a regex.

Lexical top-3 on kept subsets (silver-n, top1, top3):
- keep len<600: coverage 46.6% of real, (225, 10.2%, 22.7%). Baseline 21.1%.
- keep len<2000: 94.3%, (485, 11.3%, 20.4%).
- keep lines<15 and len<2000: 85.7%, (440, 9.3%, 18.6%).
- keep no fence/trace, lines<15, len>=30: 88.1%, (452, 9.5%, 19.0%).
- keep len 30-1999 no fence: 93.3%, (479, 10.6%, 19.6%).
- Conclusion: abstain-by-surface-features does not raise top-3 (19-23% vs 21%). Filtering is not a free precision win.
- The only subsets with higher top-3 are SHORT prompts: len<200 (86, 18.6%, 33.7%), prior0 (141, 19.1%, 32.6%), union 38.2% of real (188, 17.0%, 29.3%). These are also where judges agree most (66.5%, 53.1%, union 57.0% vs 31.4% for the rest). Both effects share a cause: short prompts have one intent. Expect dense to scale like lexical (relative ~+50%), i.e. dense top-3 about 46% x 1.5 = ~65-70% on len<200 is an UNVERIFIED extrapolation; do not quote it.
- Circularity warning: silver requires 2 judges to agree, and those judges agree more on short prompts, so "accuracy on short prompts" is partly judge-agreement, not truth. Subset "Sonnet==NIM" top-3 32.1% (221) vs 12.8% (296) when they disagree: same confound.

Recommended gate (v0, shadow only): inject only if (len<200 OR no prior prompts in session) AND retriever top-1 score margin above threshold (margin not measured here, needs the dense scores to be saved). Covers 38.2% of real prompts; abstain 61.8%. Expected top-3 on kept (lexical, measured): 29.3%; dense: unmeasured. Honest read: the gate trades 62% coverage for a modest lift; real gain must come from input structuring, test it first. First step: change baseline_embed.py to dump per-id top-3 so subsets can be re-scored (needs network, owner approval already exists for NIM).

Dictation/structuring rules, tested with lexical top-3 on all 517 silver (full text = 21.1%):
1. Head-first: keep only the first ~300 chars as the retrieval query: 24.6% (+3.5pt); on prompts >=600 chars 25.0% vs 19.9% full (+5.1pt, n292). Best measured rule.
2. Do NOT use the last question or the tail: tail300 13.3%, last-question-sentence 14.5%. The request is at the start, ends are pasted tails. Contradicts the "extract the final ask" idea.
3. Do NOT reduce to the first sentence: 18.6% (loses context). Use head chunk, not sentence.
4. Head+tail300 combo: 23.4%, worse than head alone; so tail adds noise. Drop it.
5. Split query from payload: median prompt is 653 chars, p90 1584, 53% >=600, and agreement falls from 66.5% (<200) to 32.6% (600-1999) and 29.3% (>=2000). Route long prompts as head300 (query) plus the rest as context never sent to the retriever. Justified by rule 1 and the agreement drop. Pasted-block regex (fences, URLs, tracebacks) is NOT justified: those hit <2% of prompts and show no abstain signal.
Not justified by data: any rule about question marks (silver-rate 49.3% vs 51.6%, no signal) or truncation (inconsistent).

Caveats: silver is unverified by a human; Haiku judged only Sonnet-NIM disagreements; NIM nearly never emits engineer (1% agreement) which inflates engineer/none confusion; dense subset accuracy is not measured.
