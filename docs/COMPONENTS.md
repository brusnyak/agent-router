# Components: reuse vs build (2026-11-12)

Source: component-gatherer agent (WebFetch of GitHub API/PyPI/raw LICENSE for 40+ repos; no `gh`), my checks (`gh repo view`, local runs). Rows marked UNVERIFIED were not confirmed. Re-run `gh repo view OWNER/REPO --json stargazerCount,licenseInfo,pushedAt` before any adoption.

## 1. Verdict in one paragraph
No existing open-source router replaces our core: none routes to CLI executors (Claude Code, Codex), none has evidence gates or a privacy class, and the hosted routers (OpenRouter Auto, Not Diamond, Martian) would send private prompts to a third party. So the core stays ours, on stdlib + SQLite. What we adopt are small pieces and, above all, STRUCTURES (spec/plan formats from Anthropic and OpenAI). The value we own: the curated library, the outcome log and measured routing policy, the evidence/privacy gates, the hub/node queue.

## 2. Table
| Component | Role | Licence | Activity | Verdict |
|---|---|---|---|---|
| LiteLLM (BerriAI/litellm) | multi-provider gateway, fallback | MIT core, `enterprise/` separate | 63k stars, push 2026-11-12 | IDEAS-ONLY: no CLI executors, no gates; proxy is heavy. Our key pool already works (20 parallel calls OK) |
| RouteLLM (lm-sys) | strong/weak threshold router | Apache-2.0 | push 2024-08, stale | IDEAS-ONLY: the threshold knob = our utility score |
| semantic-router (aurelio-labs) | utterance-embedding intent routing | MIT | push 2026-11-09 | IDEAS-ONLY: our `kind.py` kNN classifier is the same idea in ~60 lines |
| claude-code-router (musistudio) | proxy for Claude Code to other models | MIT | push 2026-10 | SKIP: Node 22, wrong layer |
| OpenRouter Auto / Not Diamond / Martian | hosted routers | proprietary | n/a | SKIP: prompts leave the machine |
| hermes-jev-skills (kerpopule) | "Jev" decision model for model routing, skill selection (377 skills ~2.8 s), memory passage scoring; skills are plain SKILL.md | MIT (checked) | 1.3k stars, push 2026-11-12 | STUDY NOW: closest to the owner's "cheap decision layer instead of an LLM". Open question: is Jev a hosted TypeSafe service (privacy) or local? Read before dismissing |
| fastembed (qdrant) | local ONNX embeddings | Apache-2.0 | push 2026-11-11 | WRAP as optional extra: measured here (see section 3) |
| sqlite-vec (asg017) | vector search in SQLite | Apache-2.0 | push 2026-05 | DEAD ON THIS MACHINE: `sqlite3.Connection.enable_load_extension` is missing on the pyenv Python 3.14; keep numpy/stdlib cosine |
| jina-reranker-v2 | reranker | CC-BY-NC-4.0 | n/a | SKIP: non-commercial blocks open-source distribution |
| BGE rerankers (FlagEmbedding) | rerank | MIT code, model apache-2.0 | push 2026-10 | SKIP until the outcome log shows rerank gain (measured: local cross-encoder gave no top-3 gain) |
| promptfoo | declarative prompt/regression tests | MIT | push 2026-11-12 | WRAP, dev/CI only (Node CLI), never on the runtime path |
| inspect_ai, DeepEval, ragas | eval frameworks | MIT / Apache | active | IDEAS-ONLY / SKIP: our replay harness is ~100 lines; LLM-judge metrics cost tokens |
| mem0 | LLM-extracted memory | Apache-2.0 | 68k stars | IDEAS-ONLY: an LLM call per write; unproven gain over RAG |
| Letta, Graphiti | memory servers / graph | Apache-2.0 | active | SKIP / IDEAS-ONLY (Graphiti: copy the validity-window idea; needs a graph DB) |
| DSPy | prompt compilation | MIT | active | DEFER: needs labels first (outcome log) |
| LangGraph | StateGraph + SqliteSaver | MIT | active | see section 4 |
| DBOS, Temporal | durable workflows | MIT | active | IDEAS-ONLY / SKIP (Temporal needs a server) |
| Hermes Agent, OpenClaw | channel gateways | MIT | huge | STUDY patterns (plugin adapter, outbound nodes); Hermes already on Oracle: integration target, not a dependency |
| github/spec-kit, BMAD | spec-driven phases | MIT | active | IDEAS-ONLY: adopt the phase names |

## 3. Measured here: retrieval with no LLM (local bge-small + BM25 + RRF, 67 queries)
Kind given: hybrid top1 0.70 / top3 0.82 (NIM reasoning pipeline: 0.91 / 0.99). Kind NOT given: 0.49 / 0.66 (0.46 / 0.75 with a local cross-encoder). Deterministic scoring gets most of the way once the asset kind is known; the router must therefore classify kind first (`backbone/kind.py`), and call the model only when the margin is small (`backbone/margin.py`). Not yet measured end to end.

## 4. Where LangGraph is, honestly
Only `backbone/graph.py` uses it: StateGraph with 4 nodes (prepare, work, check, finish), conditional edges for the gate loop, and SqliteSaver checkpoints so `runs resume` continues after kill -9 (tested). It plays no part in routing or retrieval. The gatherer recommends replacing it with an ~80-line SQLite step table to cut a dependency (requirements pin only lower bounds: `langgraph>=0.1.0`, `langgraph-checkpoint-sqlite>=2.0`; PyPI latest 3.1.3). Decision: keep it for now (works, tested), pin versions, replace only when a dependency budget is set.

## 5. What remains OURS (the value)
1 Outcome log + held-out real-prompt set with owner labels (`backbone/outcomes.py`, `eval/mine_transcripts.py`); no OSS tool ships this.
2 Task class to executor policy over OUR executors, quota-aware (`backbone/utility.py`).
3 Privacy gating and approval gates (`vault_to`, P6).
4 Evidence gates and provenance (`gate_passed`, `verified`, `evidence.py`).
5 Curated bundles (`library/bundles/`, validator `eval/check_bundle.py`), deduped library (`backbone/dedupe.py`).
6 Hub/node queue with checkpoint resume, SQLite-only (`jobs.py`, `node.py`).

## 6. Master build prompt: structure to adopt (Anthropic long-running-agent harness, OpenAI Codex long-horizon + ExecPlans, Claude Code best practices, AGENTS.md)
```
SPEC.md
## Done when          exact commands + expected exit codes (the check to run)
## Goal / Non-goals / Constraints   (stdlib + SQLite core; no network in tests; no secrets in DB)
## Deliverables       file paths
## Locked decisions   with rationale (Decision Log)
## Milestones M0..Mn  each finishable in one loop: scope, owned files, acceptance, validation command, stop-and-fix rule
features.json         id, description, steps, passes:false (agents must not edit tests)
Runbook               one milestone per session, commit per milestone, run validation after each
Living docs           Progress | Surprises & Discoveries | Decision Log | Outcomes & Retrospective
Out of scope + approval gates (push, send, spend, delete)
AGENTS.md             commands, layout, gate names; under 32 KiB
```
Rule from the sources: interview until the spec can be written, write it to a file, build in a fresh session; one feature per session; the check to run is part of the prompt.
