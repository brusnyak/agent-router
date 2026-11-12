# Stack for mostly-no-LLM decisions (2026-11-12)

Source: researcher agent (primary pages: arXiv, HF model cards, repos; figures as reported, not reproduced) + my local measurements (marked MEASURED). Supersedes the dependency question in `VISION.md` section 7.

## Layers
| Layer | Component | Licence (verified by gatherer) | Weight | Status |
|---|---|---|---|---|
| L0 gates | own regex/schema/keyword rules (~20, from logs): destructive/ambiguous => ask; chit-chat => inject nothing | n/a | 0 | to build |
| L1 embed | BAAI/bge-small-en-v1.5 via onnxruntime (fastembed or raw onnxruntime+tokenizers), no torch | MIT | 33M params, ~134 MB fp32 | MEASURED Mac: 9.3 ms p50 / 12.2 ms p95 per query. Oracle: onnxruntime/numpy/fastembed NOT installed yet |
| L1 classify | centroid / kNN / logistic regression on L1 vectors, numpy only | n/a | ~100 lines | to build; task class (9) and bundle, NOT asset kind (kind-first measured 0.31 vs 0.36 baseline) |
| L2 lexical | SQLite FTS5 bm25 over library, vault and project docs | public domain | 0 | MEASURED: FTS5 present on Mac (sqlite 3.54) and Oracle (aarch64, py3.12) |
| L2 rerank | cross-encoder; MiniLM ms-marco (licence UNVERIFIED) or bge-reranker-v2-m3 (Apache-2.0, 0.6B) | see left | MiniLM small | MEASURED Mac: MiniLM 300 ms for 20 candidates; gave no top-3 gain on our 67 queries => OFF until the outcome log says otherwise |
| L3 gate | margin / conformal threshold decides: act, ask the owner, or call an LLM | n/a | 0 | `backbone/margin.py` exists (worker-built); needs calibration data |
| L4 learning | Beta posterior / LinUCB per route from accept-reject outcomes | n/a | 0 | `backbone/outcomes.py`, `utility.py` exist; not wired |
| LLM | only on L3 "uncertain", for dictation structuring, and as the executors | n/a | n/a | existing key pool, workers |

Rejected: Arch-Router-1.5B (Katanemo Community Licence, commercial use needs a separate licence: not open-source distributable; its paper's 93.17% routing score is self-reported on GPU, 51 ms). SetFit at runtime (needs torch; use offline only). ColBERT/SPLADE (corpus too small). jina reranker (CC-BY-NC). sqlite-vec (cannot load extensions on the pyenv Python 3.14: MEASURED earlier). Hosted routers and Jev (cloud API; the user turn leaves the machine).

## Numbers worth knowing (reported by sources, not reproduced)
- Anthropic contextual retrieval: failure rate 5.7% -> 3.7% (contextual embeddings) -> 2.9% (+ contextual BM25) -> 1.9% (+ reranker); contextualising chunks is an index-time LLM cost (~$1.02 per M doc tokens) so it needs a local or cleared model.
- RouteLLM: tens of thousands of labels (80k arena battles); our 100-500 label regime is far below it. Hybrid LLM: up to 40% fewer large-model calls; FrugalGPT: up to 98% cost cut: vendor numbers on their own benchmarks.
- Conformal abstention: guarantee holds for any n under i.i.d., guideline ~1000 calibration points (500 in the paper's example); owner traffic drifts, so treat as a heuristic. SetFit: works from 8 examples per class on one dataset only.
- No primary curve exists for "100-500 labelled examples router accuracy": MUST be measured on the owner's data (stratified 5-fold CV).

## Minimum-data plan (assumptions flagged)
L0: 0 labels (from 2-4 weeks of logs). L1 class/bundle: 20-40 labelled prompts per class before trusting (assumed; verify with 5-fold CV per class). L3 gate: 200-500 held-out labels (wide margins until then, i.e. it will ask/call the LLM more). L4 bandit: ~30-50 outcomes per route (assumed).
Labels come from: the 949 mined prompts (eval/heldout, local), owner spot-check of ~50, and the outcome log in shadow mode.

## Open unknowns, in order of decision impact
1 Accuracy of a 100-500-label task-class router on the owner's prompts (measure first). 2 Rerank value (measure with outcome log). 3 Multilingual need (bge-small is English-only; owner writes some non-English). 4 Oracle install of onnxruntime/numpy (ARM wheels expected, UNVERIFIED). 5 Licences of sentencepiece, sklearn extras, Xenova rerank models.
