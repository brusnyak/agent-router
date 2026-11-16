# Agent Router — Two-Horizon Plan

**Status:** operational foundation complete. Horizon 1 = make it useful right now. Horizon 2 = open-source-worthy product.

## Current state (verified)

- Router runs `backbone run/ask/plan/discover/doctor`; `nim-chat` lane verified (`ROUTER_OK`)
- Skill catalog: 150 skills indexed (was 100); Gemini removed from all config/code
- Lanes: 17, with partial skill→lane binding
- RAG: hybrid BM25 + dense NIM embeddings, SQLite, wired into `core.py` resolve
- Graph: LangGraph-style prepare→work→check→critic→finish with SQLite checkpointer
- Library bundles: 6 (session-memory, job-stack-research, lead-icp-offer, gated-build, evidence-research, product-review)
- Enforcement + shadow hooks installed; bandit Thompson sampling active
- Tests: 209 pass; 4 pre-existing failures in `keys.py`/`graph.py` (unmodified by this plan)

---

## Horizon 1 — Operational now

**Goal:** make the router useful immediately for extra reasoning, proper identification of things, and orchestration — usable by agents and the owner directly.

### 1.1 Expand library bundles for activation-gap skills

The librarian report (`docs/archive/research/librarian-2026-11-13.md`) flags skills with demand but zero usage (`activation-gap`):
- `lead-generation` (demand 45), `icp-qualification` (demand 1), `niche-scoring` (demand 1)
- `orchestration` (demand 21), `delegation-and-batch` (demand 27), `vault-memory` (demand 32)
- `skill-router` (demand 24), `last30days` (demand 3)

**Action:** add a bundle per activation-gap skill in `library/bundles/`, following the `evidence-research.md` format:
- `name`, `description`, `task_class`, `triggers`
- Persona, Command (numbered procedure), Hook (before/after), Loop (iterate on gate failure, max 3), Gate (deterministic shell check), Acceptance, Failure modes

### 1.2 Complete skill→lane binding

Ensure every catalog skill is bound to at least one lane in `config/lanes.yaml`. Currently skills exist in the catalog but many lanes have empty `skills:` lists. Cross-reference the librarian report's `activation-gap` list and bind those skills to their nearest lane.

### 1.3 Activate RAG dense embeddings

Run `backbone` RAG `embed_missing()` so `rag.search` returns semantic (dense) results, not BM25-only. This powers "proper identification of things" — finding the right skill/bundle/prompt for a task.

### 1.4 Prompt library validation gates

Add a `prompt-validate` deterministic check to each bundle's gate: required headings present, every source has a URL + quote, no unverified claims in verified sections, conclusion is a numbered ranked list. This makes the prompt library self-checking.

### 1.5 Prefer nim-chat for read-only reasoning

Route read-only research/reasoning tasks through `@nim-chat` (verified working) to preserve claude/codex for build/write. The enforcement hook already nudges heavy tasks to the router.

### 1.6 Fix remaining test failures

The 4 failures in `keys.py`/`graph.py` (`test_keypool_spreads_concurrent_long_leases`, `test_prefer_avoid`, `test_81st_waits_then_raises`, `test_keypool_failover_and_cap`) are pre-existing (those files unmodified by this plan). Investigate whether they're environment-specific or real regressions.

---

## Horizon 2 — Long-term vision (open-source worthy)

**Goal:** a publishable multi-agent orchestration product with second-brain RAG, invariant-tested routing, and a product-grade prompt library.

### 2.1 Multi-agent orchestration DAG

Layer fan-out/fan-in workflows on top of lanes (LangGraph/CrewAI/Swarm patterns researched):
- DAG definitions: task A → task B → task C with parallel fan-out and join
- Result synthesis: combine worker outputs into a final answer
- Checkpoint/resume: already partially in `backbone/graph.py` (LangGraph SQLite checkpointer)

### 2.2 ECC/agency skill catalog ingestion

Ingest 50+ ECC personas (`~/Developer/ecc-reference/agents/`) and 200+ agency agents (`~/.agent-skills/vendor/msitarzewski_agency-agents/`) as catalog skills with `persona_file` bindings, routable via NIM (nim1/nim2/nim3).

### 2.3 Second-brain/vault RAG

Extend RAG to index `~/memory-vault/` pages so the router can extract resources, skills, and decisions from the owner's second brain. Cross-reference vault pages with skill catalog.

### 2.4 Invariant/test suite

Implement meta-router ROUTER_BIBLE pattern:
- Invariants-as-tests (deterministic LLM-free hot path, non-inferiority margin, eval-before-promotion)
- Complexity ratchet (LOC budget)
- Operator overrides outrank autonomous signals

### 2.5 Prompt library product

Publishable prompt registry with:
- Scoring (usage, demand, cosine similarity to nearest skill)
- Activation-gap tracking
- Librarian-driven gap closure (propose-only catalog report)
- Versioning and changelog

---

## How to consume

`backbone run @nim-chat "<task>"` — read-only NIM chat
`backbone run @claude "<task>"` — build/write with escalation lock
`backbone plan --table` — see bandit-learned worker picks per task class
`backbone doctor` — probe worker usability
`backbone discover` — re-scan machine capabilities

---

**Open questions for the owner:**
- Priority order of Horizon 1 bundles?
- Whether to invest in Horizon 2 orchestration DAG before Horizon 1 is complete?
- Open-source repo visibility (currently private `brusnyak/agent-router`)?
