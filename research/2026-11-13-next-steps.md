# Next steps: router research (2026-11-13)

Read-only browser pass. Each number quoted from the page it cites. Quoted lines are from the browser read this session (ego-browser, one tab at a time, closed after each).

## Sub-task 1: LLM tool/skill selection from vague prompts

| # | Source | URL | Quoted line (number) | Relevance to our plan | Verdict | Design change |
|---|---|---|---|---|---|---|
| 1 | ToolRet (tool retrieval benchmark, 2025) | https://arxiv.org/abs/2503.01763 | "ToolRet, a heterogeneous tool retrieval benchmark comprising 7.6k diverse retrieval tasks, and a corpus of 43k tools"; "Surprisingly, even the models with strong performance in conventional IR benchmarks, exhibit poor performance on ToolRet." | Our 11%/25% top-1 is consistent with the paper's finding that generic IR models fail on tools. Their training set (200k+) is a reason to fine-tune a small reranker later. | TEST | Keep the dense top-3 as a shortlist, and log our own per-query recall@3 as the baseline before any model change. |
| 2 | HyDE (hypothetical document embeddings) | https://arxiv.org/abs/2212.10496 | "HyDE significantly outperforms the state-of-the-art unsupervised dense retriever Contriever and shows strong performance comparable to fine-tuned retrievers" (no number in abstract) | Our prompts are vague. Generating a hypothetical "which skill would serve this" description before embedding targets the vague-prompt gap. | TEST | Add one query-rewrite step: LLM writes a 1-2 sentence skill-intent description, embed that alongside the raw prompt, measure top-3 vs raw. |
| 3 | RankGPT (LLM as reranker) | https://arxiv.org/abs/2304.09542 | "a distilled 440M model outperforms a 3B supervised model on the BEIR benchmark." | Supports the plan's NIM reranker step. Small distilled rerankers can beat bigger supervised ones, so a small model may be enough. | ADOPT (as a pattern) | Rerank only the top-3 shortlist (not the full catalog) with the NIM reranker; keep the LLM decider as a second opinion only where the reranker margin is small. |
| 4 | Kadavath et al., "Language Models (Mostly) Know What They Know" | https://arxiv.org/abs/2207.05221 | "We first show that larger models are well-calibrated on diverse multiple choice and true/false questions when they are provided in the right format." | Basis for the confidence gate: ask the decider for P(True) on its top-1 choice instead of trusting raw scores. | TEST | Gate: inject context only if decider P(True) >= threshold tuned on the silver set; otherwise inject nothing (abstain). |
| 5 | Anthropic Agent Skills overview | https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview | "Level 1: Metadata\tAlways (at startup)\t~100 tokens per Skill\tname and description from YAML frontmatter" ; "Level 2: Instructions ... Under 5k tokens" | Skill selection runs off the name+description frontmatter. Our router's candidate text should be the same frontmatter, not the SKILL.md body. | ADOPT | Index only name + description per skill for retrieval; the hook injects the chosen SKILL.md body, not the whole skill. |
| 6 | Anthropic tool search tool (vendor doc) | https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool | "Tool selection accuracy: Claude's ability to pick the right tool degrades once you exceed 30–50 available tools." ; "Tool search typically reduces this by over 85 percent, loading only the 3–5 tools Claude needs for a given request." | Vendor claim, not measured by us. Our catalog size (count unverified) decides whether a shortlist step is needed at all. | TEST (vendor claim) | Count our skills+agents; if above 30-50, keep the top-3 shortlist; if below, test sending the full catalog to the decider. |
| 7 | ToolLLM | https://arxiv.org/abs/2307.16789 | Title: "Facilitating Large Language Models to Master 16000+ Real-world APIs" | Shows API-scale tool use is a retrieval-first problem; no selection-accuracy number on the abstract page. | SKIP (no number to use) | None. |

Failed/no-number pages: HyDE abstract has no retrieval % (numbers are in tables, not read). ToolRet top-1 numbers are in the body table, not read this session. Both marked unverified for exact figures.

Sub-task 1 numbers we can cite: 7.6k tasks / 43k tools (ToolRet); 440M vs 3B (RankGPT); 30-50 tools and 85% (Anthropic vendor); ~100 tokens metadata (Anthropic skills doc). Every other figure: unverified.

## Sub-task 2: evaluating with noisy LLM-judge labels

| # | Source | URL | Quoted line (number) | Relevance | Verdict | Design change |
|---|---|---|---|---|---|---|
| S1 | MT-Bench / Chatbot Arena (Zheng et al.) | https://arxiv.org/abs/2306.05685 | "achieving over 80% agreement, the same level of agreement between humans." ; "Position bias is when an LLM exhibits a propensity to favor certain positions over others." | Judge agreement ~80% with humans for GPT-4-class judges; our 47% judge-judge exact agreement is much lower, so labels are noisy. Position bias applies to our judge prompts. | ADOPT | Randomize/swap candidate order in every judge call; report judge agreement per pair. |
| S2 | Self-preference bias (Wataoka et al.) | https://arxiv.org/abs/2410.21819 | "Our experimental results demonstrate that GPT-4 exhibits a significant degree of self-preference bias." ; "the self-preference bias exists because LLMs prefer texts more familiar to them." | Our 3 judges may favor their own model's picks. Matters if the decider model is also one of the judges. | ADOPT | Do not let a judge grade its own model's choice; use a judge from a different family than the decider for the 3rd vote. |
| S3 | Hallgren 2012, IRR tutorial (Tutorials in Quantitative Methods for Psychology) | https://pmc.ncbi.nlm.nih.gov/articles/PMC3402032/ | "Landis and Koch (1977) provide guidelines for interpreting kappa values, with values from 0.0 to 0.2 indicating slight agreement, 0.21 to 0.40 indicating fair agreement, 0.41 to 0.60 indicating moderate agreement" ; "The first effect appears when the marginal distributions ... called the prevalence problem, which typically causes kappa estimates to be unrepresentatively low." | Kappa for our 3 judges; prevalence problem applies if most silver labels are one class. | ADOPT | Report Fleiss kappa over the 3 judges plus the class prevalence; if kappa < 0.4 do not treat silver as ground truth. |
| S4 | NIST e-Handbook 7.2.4.1 (Wilson/Agresti-Coull CI) | https://itl.nist.gov/div898/handbook/prc/section2/prc241.htm | "The Wilson method for calculating confidence intervals for proportions ... is based on inverting the hypothesis test" ; "symmetical confidence limits that are approximated using the normal distribution may not be accurate enough" for small n | Interval method for the human-checked precision estimate. | ADOPT | Use the Wilson interval, not Wald, when checked n is small or precision is near 0 or 1. |
| S5 | Lewis & Gale 1994, uncertainty sampling | https://arxiv.org/abs/cmp-lg/9407020 | "This method, which we call uncertainty sampling, reduced by as much as 500-fold the amount of training data that would have to be manually classified" | Basis for picking which items the owner checks: lowest judge margin / judge disagreement first. | ADOPT | Spot-check selection: judge-disagreement items first, then random items for the unbiased precision estimate. |
| S6 | Settles, Active Learning Literature Survey (tech report) | https://minds.wisconsin.edu/handle/1793/60660 | Abstract page only: "an overview of the query strategy frameworks proposed in the literature to date." (no number read) | Survey of query strategies (uncertainty, query-by-committee). | TEST | Read the full PDF before choosing a query strategy beyond uncertainty sampling; PDF text was not readable via browser. |

Not verified: exact MT-Bench position-bias percentages (body table not read), exact self-preference metric values, Fleiss kappa formula (only Cohen kappa worked example read: "κ = (0.79 – 0.50)/(1 - 0.50) = 0.58" from S3).

### Sample size for precision within +-10 points (our 517 silver labels)

Formula, normal approximation with finite-population correction (textbook derivation from the half-width z*sqrt(p(1-p)/n) <= E):

- n0 = z^2 * p(1-p) / E^2, with z = 1.96 (95%), E = 0.10
- n = n0 / (1 + (n0 - 1) / N), N = 517

Computed this session (python3 -I):

| assumed precision p | n0 (infinite) | n (N=517) |
|---|---|---|
| 0.50 (worst case) | 96.04 -> 97 | 81.13 -> **82** |
| 0.80 | 61.47 -> 62 | 55.03 -> **56** |
| 0.90 | 34.57 -> 35 | 32.47 -> **33** |

Answer: 82 human-checked items gives +-10 points at 95% in the worst case (p = 0.5). If we expect ~80% precision, 56 suffices. Use Wilson (S4) for the final CI.

### Recommended spot-check protocol (1 hour owner time)

1. Pre-compute per item: judge votes (3), position-swapped rerun agreement, and decider margin. (0 owner time.)
2. Owner labels 82 items in one block of ~50 min (~35 s/item for a binary yes/no with the judge rationale hidden):
   - 40 from judge-disagreement items (2-of-3 split or unanimous-but-low-margin): uncertainty sampling per S5.
   - 42 random from the 517 for the unbiased precision estimate (formula above).
   - Shuffle; owner does not see which judge said what.
3. Report: precision on random 42 with Wilson 95% CI (the unbiased number); precision on the disagreement 40 reported separately, never pooled.
4. If the Wilson lower bound on silver precision < 0.7, stop trusting silver for threshold tuning and relabel the disagreement pool first.
5. Budget: 82 items, ~50 min, 10 min for setup and the report. Owner does not edit labels in place; writes a CSV of verdicts only.
