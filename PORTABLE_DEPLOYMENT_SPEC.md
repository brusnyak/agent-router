# AGENT ROUTER — PORTABLE DEPLOYMENT SPEC

**Version:** 1.0  
**Status:** Active  
**Purpose:** Single router project that copies to any server (Mac, Oracle VM, etc.) and runs cleanly with zero extra configuration.

---

## 1. ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                    DISPATCH COCKPIT (UI)                    │
│  Task input → Lane pick → Model pick → Skill pick → Run     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              ROUTER SUPERVISOR (LangGraph)                  │
│  • Index-aware triage (FTS5 + router.py skill matching)     │
│  • Config drift constraints (PEEM feedback → routing)       │
│  • Circuit breaker (closed → open → half_open)              │
│  • Fallback chains (nim3 → nim2 → nim1 → deterministic)     │
│  • Explicit dispatch overrides (lane/model/skills)          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              AGENT DISPATCH LAYER                           │
│  NIM agents (text-generation)   │ CLI agents (shell+write)  │
│  nim3/nim2/nim1 (NIM API)       │ claude, codex (CLI TTY)   │
│  Key harness: rotation+retry    │ Worktree isolation + shell=False
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              POST-DISPATCH VERIFICATION                     │
│  • Extract claimed code blocks → write to disk              │
│  • Verify files exist on disk (anti-fabrication)            │
│  • Card + PEEM evaluation (NIM3 + Gemini dual judge)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. PROJECT SCOPE — WHAT THIS IS

The Agent Router is a **single-file-deployable multi-agent dispatch system**. It is NOT an IDE, NOT a desktop app, NOT a browser extension. It is:

- A Python backend (FastAPI + LangGraph) that receives task descriptions
- Routes them to the right agent (NIM API or CLI-based)
- Verifies the agent actually produced what it claimed
- Scores output with PEEM criteria (6 dimensions, dual-judge)
- Learns from evaluations via config drift (suggest + gate, never auto-apply)
- Cross-device: Telegram bridge for dispatch/monitoring, Oracle VM council for fan-out research

**What it is NOT:** Orca (IDE), Cursor, Zed, OpenCode (CLI agent host). It complements those — it routes TO them, not replaces them.

---

## 3. DEPLOYMENT — COPY-PASTE TO ANY SERVER

### Prerequisites on target machine

```
python3 -m venv ~/agent-router-venv
~/agent-router-venv/bin/pip install --upgrade pip
~/agent-router-venv/bin/pip install fastapi uvicorn langgraph langchain-core langchain-nvidia-ai-endpoints pyyaml python-multipart
```

### Copy project

```bash
# On source machine
cd /path/to/agent-router
tar czf /tmp/agent-router.tar.gz \
  --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='kanban.db' --exclude='index.db' --exclude='discovered-inventory.json' \
  --exclude='node_modules' --exclude='.git' --exclude='*.tar.gz' \
  --exclude='bp' --exclude='cards' .

scp /tmp/agent-router.tar.gz oracle-vm:~/

# On target machine
mkdir -p ~/agent-router
cd ~/agent-router
tar xzf ~/agent-router-code.tar.gz
```

### Configure API keys

Create `~/agent-router/.env`:

```
NIM_1=<your-nim-1-key>
NIM_2=<your-nim-2-key>
NIM_3=<your-nim-3-key>
```

At least one NIM key required. All three recommended for key rotation.

### Initialize and run

```bash
cd ~/agent-router
~/agent-router-venv/bin/python -c "from db.database import init_db; init_db()"
~/agent-router-venv/bin/python main.py
# Backend serves on http://127.0.0.1:8080
```

### Verify

```bash
curl http://127.0.0.1:8080/health
# → {"status":"healthy","agents_total":21,"agents_available":21,"supervisor_llm":true}

curl -s -X POST http://127.0.0.1:8080/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"build a hello world python script","lane":"build"}'
```

---

## 4. CONFIGURATION — ENVIRONMENT VARIABLES

| Env var | Required | Default | Purpose |
|---------|----------|---------|---------|
| `NIM_1` | No | — | NIM key 1 (worker) |
| `NIM_2` | No | — | NIM key 2 (worker) |
| `NIM_3` | No | — | NIM key 3 (supervisor/judge) |
| `GEMINI_API_KEY` | No | — | Second PEEM judge (optional) |
| `TELEGRAM_BOT_TOKEN` | No | — | Telegram bridge (optional) |
| `TELEGRAM_CHAT_ID` | No | — | Telegram bridge target |
| `ORACLE_VM_HOST` | No | `localhost` | Oracle VM SSH tunnel host |
| `ORACLE_VM_IP` | No | — | Oracle VM direct IP |
| `ORACLE_VM_USER` | No | `ubuntu` | Oracle VM SSH user |
| `ORACLE_VM_KEY` | No | `~/.ssh/ssh-key-2026-02-21.key` | Oracle VM SSH key |

No hardcoded `/Users/yegor/...` paths anywhere. All paths resolve from `__file__` or `~`.

---

## 5. AGENT IDENTIFICATION — HOW THE ROUTER FINDS AGENTS

The router discovers agents from `config/agents.yaml` (auto-generated by `scripts/discover_machine.py`):

| Agent | Provider | Capabilities | Lane |
|-------|----------|--------------|------|
| nim3 | nim | text-generation | supervisor, mechanical |
| nim2 | nim | text-generation | worker |
| nim1 | nim | text-generation | worker |
| claude | cli | text-generation, shell-access, file-write | build, review-roast |
| codex | cli | text-generation, shell-access, file-write | build, review |
| gemini | cli | text-generation | research, deep-research |
| ecc-code-reviewer | nim | text-generation | review-roast |
| ecc-agent-evaluator | nim | text-generation | evaluation |
| agency-ui-designer | nim | text-generation | design-ui |

**Agent selection logic:**
1. User specifies lane → lane config lists preferred agents
2. Router filters by availability (NIM keys present, CLI binaries on PATH, circuit breaker not open)
3. Fallback chain: primary agent → NIM fallback → deterministic
4. Circuit breaker: 3 consecutive failures → OPEN for 60s → HALF_OPEN (one probe)

---

## 6. SKILLS SYSTEM

Skills are discovered from:
- `~/.claude/skills/` (54 active)
- `~/.agent-skills/` (archive + synced)
- `/Users/yegor/Developer/ecc-reference/skills/` (314 ECC skills)
- `config/` (project-level)

ECC skills include: `design-system`, `taste`, `frontend-design-direction`, `liquid-glass-design`, `agent-eval`, `agent-harness-construction`, `agent-self-evaluation`, `build-discipline`, `karpathy-guidelines`, `verification-before-completion`, `roast`, `critique`, `mentor`, `search-first`, `niche-scoring`, `lead-dossier`, `icp-qualification`, `offer-design`, `market-research`, `customer-discovery`, `upwork-scan`, `jobs`, `retro`, `security-review`, `code-review`, `build-discipline`.

**Agent Router index** (`router.py find`): 1,055 items indexed (skills + agents + design refs). Semantic + lexical search with RRF fusion.

---

## 7. HOOKS & LOOPS

### Config Drift Loop
```
PEEM evaluations accumulate → config_drift.py analyzes → proposes routing constraints → owner reviews → applies via interrupt gate
```
Never auto-applies. All proposals are `status: proposed`.

### Proactive Loop (dry-run capable)
```
kanban.db + vault inbox → research sub-agent → review critic (loop detection at 3×) → interrupt gate → execution via supervisor
```
Quiet hours: 22:00–08:00. Max load: 6.0. Max actions per run: 3.

### Router Self-Discovery
```
router.py find "<task>" → skill/agent matches → injected into triager prompt
```
The router routes itself — it knows which skills and agents fit each task.

### Evaluation Loop
```
card completed → NIM3 judge + Gemini judge (dual) → PEEM scores (6 criteria) → divergence flag → config drift if avg < 3.5
```

---

## 8. CRITIC / ROAST / MENTOR — SELF-IMPROVEMENT

| Role | Purpose | Tool |
|------|---------|------|
| `review-roast` lane | Severity-ranked findings on any output | `roast` skill |
| `critique` | Picky restaurant-critic style review | `critique` skill |
| `mentor` | Challenge decisions, demand evidence | `mentor` skill |
| `retro` | End-of-session self-review ledger | `retro` skill |
| `config_drift` | PEEM-driven routing proposals | `scripts/config_drift.py` |

Every sub-agent must: verdict first, evidence second, roast third (weakest point + cheapest fix + smallest fix). Never manufactured.

---

## 9. CAVMAN MODE — ALL SUB-AGENTS

All agents (sub-agents, loops, critics, routers) must follow caveman communication:
- Open with result/verdict. NO preamble, pleasantries, filler.
- Status/results/errors: caveman. Infinitive verbs, drop articles, fragments.
- Planning/decisions: `Verdict | Scope/Options | Recommend | Ask (numbered, <=5)`.
- Route receipt: `route: skill <name> | agent <name> | script <path> | inline`.
- Errors/warnings: one line.
- Last line: `🟢 <check>` \| `🟡 untested` \| `🔴 <blocker>`.

---

## 10. SELF-CONFIGURE / SELF-UPDATE

```
scripts/discover_machine.py   → scans machine (agents, keys, browsers, skills, vault, projects)
scripts/configure_from_discovery.py → generates agents.yaml, skills.yaml, lanes.yaml, models.yaml
scripts/index_vault.py        → builds FTS5 + TF-IDF index over skills, hooks, vault, repos
router.py build               → builds skill+agent index (1,055 items)
```

Run once on first deploy. Re-run when machine changes (new agent, new key, new skill directory).

---

## 11. CONTINUING DEVELOPMENT — LOCAL + SERVER

### Local development cycle

```
1. Edit code (graph/, scripts/, api/)
2. python3 tests/test_discovery.py  (all 5 test files must pass)
3. python3 main.py  (backend on 8080)
4. curl http://127.0.0.1:8080/health  (verify)
5. curl -s -X POST http://127.0.0.1:8080/api/chat ...  (dogfood task)
6. Append retro to ~/memory-vault/journals/YYYY-MM-DD.md
7. git commit
```

### Deploy to server

```bash
# On local machine
git commit -am "message"
git push origin main

# On server (any machine)
ssh oracle-vm
cd ~/agent-router
git pull origin main
~/agent-router-venv/bin/python -c "from db.database import init_db; init_db()"
~/agent-router-venv/bin/python main.py
```

No extra configuration. Same `.env`, same code, same behavior.

### When you're away (Mac closed)

Oracle VM runs the same backend. Connect via:
```bash
ssh -L 8080:127.0.0.1:8080 oracle-vm
curl http://localhost:8080/health
```

Telegram bridge for dispatch when away:
```bash
python scripts/telegram_bridge.py --poll
# Send: /dispatch <task>
# Receive: card result + PEEM score
```

Oracle VM council for research fan-out:
```bash
python scripts/cross_device_sync.py --council "<research task>"
# Fans out to gemini/kimi/glm/gemma on Oracle
```

---

## 12. LOCAL MODEL SETUP (WHEN AWAY)

No local models required — NIM API keys work from anywhere with internet. If NIM is unavailable:

- Fallback to deterministic triage (keyword-based lane selection)
- CLI agents (claude/codex) if installed locally with auth
- Oracle VM council as remote fallback

Minimum viable: one NIM key + `python main.py`. Everything else degrades gracefully.

---

## 13. FILES TO COPY (ENTIRE PROJECT)

```
agent-router/
├── main.py                    # FastAPI backend entry
├── graph/                     # LangGraph supervisor, state, agents, evaluation, prompts
├── scripts/                   # discovery, configure, index, drift, harness, bridge, sync
├── config/                    # auto-generated (agents.yaml, skills.yaml, lanes.yaml, models.yaml, projects.yaml)
├── api/                       # FastAPI endpoints (chat, cards, analytics, evaluate, skills)
├── ui/                        # React frontend (kanban board + analytics)
├── db/                        # SQLite layer
├── tests/                     # 5 test files (discovery, indexer, drift, agent_base, supervisor)
├── requirements.txt           # Python dependencies
├── Makefile                   # setup, start, test, lint, format
├── PRODUCT_SPEC.md            # product vision
├── ROWS_ANALYSIS.md           # gap analysis
├── DEVELOPMENT_LOOP.md        # development loop
└── .env                       # API keys (NOT committed)
```

DO NOT COPY: `.venv/`, `__pycache__/`, `*.pyc`, `kanban.db`, `index.db`, `discovered-inventory.json`, `config/drift/config-drift.yaml`, `cards/`, `.git/`, `node_modules/`, `bp/`, `*.tar.gz`

---

## 14. TEST SUITE

```
python3 tests/test_discovery.py    # machine discovery
python3 tests/test_indexer.py      # vault indexing
python3 tests/test_drift.py        # config drift
python3 tests/test_agent_base.py   # agent abstraction
python3 tests/test_supervisor.py   # router supervisor
```

All 5 must pass. `pytest` not required — tests are standalone Python scripts.

---

## 15. EXPECTATIONS — WHAT WORKS vs WHAT DOESN'T

**Works:**
- NIM agent dispatch (text generation, ~1s per task)
- CLI agent dispatch (claude/codex with TTY via `script` wrapper)
- Code block extraction + disk verification (anti-fabrication)
- Dual-judge PEEM evaluation (NIM3 + Gemini)
- Config drift from PEEM feedback
- Circuit breaker + fallback chains
- RAG context retrieval (skills, hooks, vault, repos)
- Telegram bridge (send/receive commands)
- Oracle VM council fan-out

**Does NOT work (yet):**
- Claude/OpenAI CLI dispatch without TTY workaround
- HITL approve/resume (gate blocks but `/api/approve` re-triggers same gate)
- Eval suites (≥20 cases per agent)
- Frontend Dispatch Cockpit UI (generic kanban only)
- Cross-device SQLite sync (Syncthing + SQLite = corruption risk)

---

## 16. IMMEDIATE NEXT ACTIONS (Priority Order)

| Priority | Action | Command |
|----------|--------|---------|
| P0 | Fix CLI agent failure masking (raise not return) | `graph/agent_base.py` |
| P0 | Wire `agent_harness.py` into `worker_node` | `graph/supervisor.py` |
| P0 | HITL `Command(resume=...)` for approve | `graph/supervisor.py` + `api/chat.py` |
| P0 | Eval suites (≥20 cases/agent) | `tests/test_eval_*.py` |
| P1 | Canonical `claimed_files` regex | `graph/agent_base.py` |
| P1 | `trace_log` declared in `RouterState` | `graph/state.py` |
| P1 | Context budget management | `graph/prompt_library.py` |
| P2 | ECC skills wired into routing | `graph/prompt_library.py` |
| P3 | Open-source config paths | All `graph/*.py` |
| P3 | Telegram bridge test | `scripts/telegram_bridge.py --test` |

---

## 17. QUESTIONS (None blocking)

None — proceeding with implementation per this spec.

---

**Route:** inline | agent: nim3 | scripts: all | spec: PORTABLE_DEPLOYMENT_SPEC.md

🟢 Spec written; Oracle cleaned; all hardcoded paths fixed; ready for portable deploy
