# Agent Router — Horizon 2 Design

**Prerequisite:** Horizon 1 complete (150 skills, 17 lanes, nim-chat lane verified, RAG hybrid search, library bundles).

**Goal:** publishable multi-agent orchestration product — DAG workflows, ECC/agency catalog ingestion, second-brain RAG, invariant test suite, prompt library product.

---

## 2.1 Multi-agent orchestration DAG

### Problem
Router currently dispatches one task → one worker → one result. No fan-out/fan-in, no workflow definition, no result synthesis.

### Design
Add a `Workflow` model and a `WorkflowRunner` that executes DAGs over lanes/workers.

**Data model** (`config/workflows.yaml`):
```yaml
version: 1
workflows:
  - id: research-and-write
    description: Research a topic, then write a report
    steps:
      - id: research
        worker: nim-chat
        gate: "grep -qE 'http' <output>"
        depends_on: []
      - id: write
        worker: claude
        gate: "test -f report.md"
        depends_on: [research]
    fan_out: [research]   # steps that can run in parallel
    synthesize: claude    # worker that combines results
```

**Interfaces** (new module `backbone/workflow.py`):
```python
class WorkflowStep:
    id: str
    worker: str        # lane/worker id
    gate: str          # deterministic shell command
    depends_on: List[str]
    
class Workflow:
    id: str
    steps: List[WorkflowStep]
    fan_out: List[str]      # step ids that run in parallel
    synthesize: str|None    # worker id for final combination, or None
    
class WorkflowResult:
    step_results: Dict[str, Result]   # per-step worker output
    synthesis: str|None               # combined output
    ok: bool                          # all gates passed
    
def load_workflows(path) -> Dict[str, Workflow]
def run_workflow(bb, workflow_id, prompt, cwd) -> WorkflowResult
```

**Execution semantics:**
- Topological sort of steps by `depends_on`
- Steps in `fan_out` with no unmet dependencies run in parallel (ThreadPoolExecutor)
- Each step runs via `bb._dispatch(worker, task, cwd, read_only, attempt)` then runs its gate
- Gate failure → step marked failed; dependents skipped; synthesis uses only passed steps
- Synthesis step (if set) receives all step outputs and produces final answer

**CLI grammar:** `backbone workflow <workflow-id> "<prompt>"`

### Files to create/modify
- Create: `backbone/workflow.py` (Workflow model, runner, loader)
- Modify: `backbone/core.py` (add `workflow` dispatch kind)
- Create: `config/workflows.yaml` (initial workflows: research-and-write, build-and-review, lead-qualify-and-outreach)
- Create: `tests/test_workflow.py` (DAG execution, gate failure skips dependents, synthesis)

---

## 2.2 ECC/agency skill catalog ingestion

### Problem
50+ ECC personas (`~/Developer/ecc-reference/agents/`) and 200+ agency agents (`~/.agent-skills/vendor/msitarzewski_agency-agents/`) exist as NIM persona entries in `agents.yaml` but aren't cataloged as discoverable skills.

### Design
Add ingestion that reads persona `.md` files and creates catalog skill entries with `persona_file` bindings.

**Interfaces** (new module `backbone/catalog_ingest.py`):
```python
def ingest_ecc_agents(ecc_dir) -> List[dict]      # one skill per persona .md
def ingest_agency_agents(agency_dir) -> List[dict] # one skill per agent dir
def bind_skills_to_lanes(skills, lanes) -> Dict[str, List[str]]  # skill id -> lane ids
```

Each ingested skill:
```yaml
- id: ecc-code-reviewer
  path: ~/Developer/ecc-reference/agents/code-reviewer.md
  category: ecc-persona
  description: <first paragraph of persona file>
  persona_file: ~/Developer/ecc-reference/agents/code-reviewer.md
  _source: ecc-reference
  _discovered_at: <iso>
```

**CLI:** `backbone catalog ingest` (re-scans ecc-reference + agency dirs, updates skills.yaml)

### Files to create/modify
- Create: `backbone/catalog_ingest.py`
- Modify: `scripts/configure_from_discovery.py` (call ingestors in main)
- Create: `tests/test_catalog_ingest.py`

---

## 2.3 Second-brain/vault RAG indexing

### Problem
RAG currently indexes only `library/bundles/` and skills. Can't extract resources from `~/memory-vault/`.

### Design
Extend `Rag` to index vault pages (`~/memory-vault/pages/*.md`).

**Interfaces** (extend `backbone/rag.py`):
```python
class Rag:
    def index_vault(self, vault_dir: str, limit: int = 5000) -> int
        # index .md files under vault_dir/pages/
        # extract: title, first paragraph, area::, links
        # store as library rows with kind='vault'
    def search_vault(self, query: str, k: int = 5) -> List[dict]
        # rag.search filtered to kind='vault'
```

Each vault page indexed as:
- id: `vault:<relative-path>`
- kind: `vault`
- name: page title (first H1 or filename)
- description: first paragraph
- body: full page text (first 1500 chars)
- meta: `{area: ..., links: [...], path: ...}`

**CLI:** `backbone rag index-vault` and `backbone rag search-vault "<query>"`

### Files to create/modify
- Modify: `backbone/rag.py` (add index_vault, search_vault)
- Create: `tests/test_rag_vault.py`

---

## 2.4 Invariant/test suite (ROUTER_BIBLE pattern)

### Problem
No invariant tests, no complexity ratchet, no eval-before-promotion gate.

### Design
Adopt meta-router's invariant-as-tests pattern.

**Tests to add** (`tests/test_invariants.py`):
- `test_router_hot_path_no_network` — `plan()` and `classify()` make no network calls
- `test_bandit_non_inferiority_margin` — bandit pick respects quality+cost scoring, no blind cost-only selection
- `test_eval_before_promotion` — any change to routing logic requires gate pass on heldout set
- `test_operator_override_wins` — `routes.yaml` manual entries override bandit when both present
- `test_complexity_ratchet` — backbone LOC under committed budget (track in `tests/complexity_budget.json`)
- `test_unknown_cells_counted_not_imputed` — bandit cells with no history use prior, not sibling history

**Files to create/modify**
- Create: `tests/test_invariants.py`
- Create: `tests/complexity_budget.json`
- Modify: `tests/` CI config to run invariants on every change

---

## 2.5 Prompt library product

### Problem
Prompt library is 13 bundles with no scoring, no activation-gap tracking, no librarian-driven gap closure.

### Design
Add scoring and librarian integration.

**Interfaces** (extend `scripts/librarian.py` or create `scripts/prompt_catalog.py`):
```python
def score_skill(skill) -> dict        # usage, demand, cos_similarity, activation_gap
def librarian_report() -> str         # propose-only catalog report
def suggest_lane_binding(skill_id) -> str  # nearest lane with capacity
```

**Scoring fields** (add to skills.yaml entries):
- `usage`: int (from enforce/receipt logs)
- `demand`: int (from librarian analysis)
- `cos`: float (cosine similarity to nearest skill)
- `activation_gap`: bool (demand > 0 and usage == 0)

**CLI:** `backbone librarian --write` (writes propose-only report to `docs/archive/research/`)

### Files to create/modify
- Modify: `scripts/librarian.py` (add scoring + suggestion)
- Modify: `config/skills.yaml` (add usage/demand/cos fields)
- Create: `tests/test_librarian_scoring.py`

---

## Implementation order (recommended)

| Phase | Item | Est. effort | Dependencies |
|-------|------|-------------|--------------|
| 2A | Workflow DAG (`backbone/workflow.py` + CLI) | 1-2 sessions | Horizon 1 lanes + nim-chat |
| 2B | ECC/agency catalog ingestion | 1 session | skills.yaml tilde paths (done) |
| 2C | Vault RAG indexing | 1 session | rag.py exists |
| 2D | Invariant test suite | 1-2 sessions | none |
| 2E | Prompt library scoring + librarian | 1 session | enforce/receipt logs exist |

**Recommended start:** 2A (Workflow DAG) — it's the most valuable for "extra reasoning and orchestration" and builds directly on Horizon 1's lanes + nim-chat.

---

## Open questions for the owner

1. Start with 2A (Workflow DAG) or 2B (ECC/agency ingestion)?
2. Should Horizon 2 be open-source (repo currently private `brusnyak/agent-router`)?
3. Any specific workflows to define first (research-and-write, build-and-review, lead-qualify-and-outreach, or custom)?
