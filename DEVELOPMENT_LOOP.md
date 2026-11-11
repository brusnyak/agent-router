# Agent Router — Deliberate Spec & Development Loop

**Version:** 1.0  
**Date:** 2026-11-11  
**Status:** Active  
**Goal:** Single unified UI (Dispatch Cockpit) that replaces context-switching between OpenCode/Orca — explicit lane, model, and skill selection with RAG context, verified outputs, PEEM scoring, and cross-device dispatch via Oracle VM council + Telegram.

---

## 1. The Vision (One Sentence)

A single chat input → explicit lane/model/skill selection → RAG-augmented prompt → agent dispatch → verified output → PEEM evaluation → config drift → all visible in one UI, dispatchable from Mac, Oracle VM council, or Telegram.

---

## 2. Architecture (Current → Target)

| Layer | Current State | Target State |
|-------|--------------|--------------|
| Backend (FastAPI + LangGraph) | ✅ Working — supervisor, eval, drift, 21 agents | Keep, add explicit dispatch params |
| NIM key harness | ✅ Built + tested (rotation, retry, backoff) | Wired into all NIM dispatch paths |
| Agent harness (write+verify) | ✅ Built — writes code blocks, verifies on disk | Wired into supervisor.worker_node |
| Circuit breaker + fallback | ✅ Built | Active on all agent dispatches |
| Observability (trace_id) | ✅ Partial — trace_log in state | Emit JSON lines to file |
| Frontend UI | ❌ Generic kanban, no cockpit | Dispatch Cockpit page |
| Cross-device (Oracle council) | ✅ Council live on port 3033 | Telegram bridge + council fan-out wired |
| Cross-device (Telegram) | ⚠️ Credentials in .env, bridge built, untested | `--test` run, then polling mode |
| Eval baseline | ❌ Missing | ≥20 cases per agent, documented |
| Open-source config | ⚠️ Partial | Zero hardcoded `/Users/yegor/` paths |

---

## 3. The Dispatch Cockpit (The One UI)

```
┌─────────────────────────────────────────────────────────────┐
│  Dispatch Cockpit  │  Model: ▼nim3  │  Lane: ▼build  │  ▶ Run │
├─────────────────────────────────────────────────────────────┤
│  Task input: _____________________________________________  │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Skills (RAG) │  │ Prompt Lib   │  │ Context      │      │
│  │ [x] build-dis│  │ [x] router   │  │ [retrieved   │      │
│  │ [x] verify-b4│  │ [x] karpathy │  │  context     │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Model Output (streaming)                            │   │
│  │ ├── Claimed files: ✅ hello.py (verified)          │   │
│  │ ├── PEEM: acc 4/5, coh 4/5, rel 4/5, ...           │   │
│  │ ├── Judge: nim3+gemini, divergence 0.2             │   │
│  │ └── Tokens: 1,200 | Latency: 6648ms                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐  │
│  │ Backlog  │ Triaging │ Running  │ Review   │ Done     │  │
│  │    12    │    3     │    1     │    0     │   98     │  │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Backend API Additions (Minimal)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/dispatch` | POST | Explicit dispatch: `{task, lane, model, skills[], project}` → full result |
| `/api/skills` | GET | List all indexed skills (600+ from skills.yaml + ECC + agency) |
| `/api/retrieve` | GET | RAG retrieval: `?q=...` → relevant skills/hooks/vault context |
| `/api/models` | GET | Already exists — expose model capabilities |
| `/api/evaluate/analytics` | GET | Already exists — PEEM per agent/model |
| `/api/approve` | POST | HITL gate approval |

**`RouterSupervisor.run()`** — add explicit overrides: `lane`, `model`, `skills`. Currently auto-selects via triager; user overrides take priority.

---

## 5. Development Loop (The Loop)

Each iteration: **Spec → Code → Test → Verify → Commit → Dogfood → Retro**

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   SPEC      │ →  │   CODE      │ →  │   TEST      │
│ (this doc)  │    │ (implement) │    │ (pytest)    │
└─────────────┘    └─────────────┘    └─────────────┘
       ▲                                           │
       │                                           ▼
┌─────────────┐    ◄────────────────────  DOGFOOD   │
│   RETRO     │ ←  │   VERIFY      │    (10 real tasks)│
│ (lessons)   │    │ (PEEM scores) │                  │
└─────────────┘    └─────────────┘    └─────────────┘
```

### Loop Steps (per iteration)

1. **Spec** — Update PRODUCT_SPEC.md / ROWS_ANALYSIS.md with next target
2. **Code** — Implement one row from ROWS_ANALYSIS.md (P0 first)
3. **Test** — `.venv/bin/python -m unittest tests.test_*` + `make test`
4. **Verify** — Backend health check, `/api/cards`, `/api/evaluate/analytics`
5. **Dogfood** — Run 1 real task through Dispatch Cockpit, capture PEEM score
6. **Commit** — Git commit with message, push to GitHub
7. **Retro** — Append one line to `~/memory-vault/journals/YYYY-MM-DD.md`

### Definition of Done (per row)

- [ ] Code implemented
- [ ] All 5 test files pass (`test_discovery`, `test_indexer`, `test_drift`, `test_agent_base`, `test_supervisor`)
- [ ] `ruff check` clean on changed files
- [ ] Backend health endpoint returns 200
- [ ] At least 1 real task dispatched through the new code path
- [ ] PEEM score recorded in `evaluations` table
- [ ] Retro entry appended to vault journal

---

## 6. Row Priority (from ROWS_ANALYSIS.md)

| Priority | Row | Gap | Score | Next Action |
|----------|-----|-----|-------|-------------|
| P0 | 9 | Code execution sandbox (TTY fix) | 20 | Fix `script` wrapper / pty for claude/codex |
| P0 | 13 | Agency agents usable | 20 | Same as #9 |
| P0 | 1 | NIM agent fabrication → supervisor integration | 10 | Wire agent_harness into worker_node + card_writer |
| P0 | 7 | Eval suites per agent | 16 | Write ≥20 test cases per agent |
| P0 | 2 | NIM API key harness | 8 | Already built — integrate into all NIM calls |
| P1 | 5 | Structured observability | 12 | Emit trace_log as JSON lines |
| P1 | 8 | HITL interface | 12 | `/api/approve` endpoint + UI buttons |
| P1 | 6 | Context budget management | 9 | Token counting + summarization |
| P1 | 10 | Frontend PEEM scorecards | 12 | Build PEEM Scorecard React component |

---

## 7. Cross-Device Dispatch (Oracle VM + Hermes + Telegram) — FREE MODELS ONLY

### Model Cost Policy (Hard Rule)
Only **free** models may be used. No paid APIs, no paid tiers.

| Model | Source | Cost | Status |
|-------|--------|------|--------|
| NIM nemotron-3.5-super-vl-120b-a12b | NVIDIA NIM free tier (NIM_1/2/3) | Free | ✅ Primary |
| Codex CLI | Local binary | Free (if auth'd) | ⚠️ Needs auth |
| Claude CLI | Local binary | Free (if auth'd) | ⚠️ Needs auth |
| Gemini API | Google | Free tier (rate-limited) | ⚠️ Secondary |
| Oracle council GLM/Kimi/Gemma | Oracle VM | Unknown/paid | ❌ **DO NOT USE** |
| Oracle council Gemini | Oracle VM | Free tier | ⚠️ Only if verified free |

**Never route to GLM, Kimi, or Gemma.** They timed out/400'd in council tests. NIM keys + local CLIs only.

### Oracle VM Council (Port 3033)
- **Status:** Live but models unreliable (GLM/Gemma timeout/400, Gemini timeout)
- **Endpoint:** `http://localhost:3033/review/api/council` (via SSH tunnel `ssh -L 3033:127.0.0.1:3033 oracle-vm`)
- **Command:** `.venv/bin/python scripts/cross_device_sync.py --council "<task>"` — **only with NIM keys, never GLM/Kimi/Gemma**
- **Use:** Fan-out research tasks to NIM models when Mac is off

### Hermes Nina Gateway (Oracle VM)
- **Status:** Running (PIDs 159830, 163511 — `hermes_cli.main gateway run --replace --accept-hooks`)
- **Use:** Hermes agent on Oracle can receive/execute tasks when Mac is off (free, self-hosted)
- **SSH tunnel:** `ssh -L 3033:127.0.0.1:3033 oracle-vm`

### Telegram Bridge
- **Status:** Built, credentials in `~/.env`, untested
- **Command:** `.venv/bin/python scripts/telegram_bridge.py --test`
- **Use:** Send card summaries, PEEM scores, drift proposals; receive `/dispatch <task>` commands (free)

### Syncthing
- **Status:** Process running (PIDs 932, 1293) but API not yet accessible on port 8384
- **Use:** Sync `kanban.db`, vault files, config between Mac and other devices (free)

---

## 8. Skills / Agents / Hooks / Systems to Use

| System | Location | Purpose |
|--------|----------|---------|
| ECC skills | `/Users/yegor/Developer/ecc-reference/skills/` (314) | Indexed via `discover_machine.py`, used for task routing |
| ECC agents | `/Users/yegor/Developer/ecc-reference/agents/` (71) | Wired into `agents.yaml` as virtual NIM agents |
| Agency agents | `/Users/yegor/.agent-skills/vendor/msitarzewski_agency-agents/` (300) | Wired into `agents.yaml` |
| Skill+Agent Router | `/Users/yegor/.agent-skills/router/router.py` | `router.py find "<task>"` → skill/agent matches; used by supervisor `_build_router_context` |
| Router index | `/Users/yegor/.memory/skill_index/` (1,055 items) | Semantic + lexical search, built with `router.py build` |
| NIM key harness | `scripts/nim_key_harness.py` | Key rotation, retry, backoff for all NIM calls |
| Agent harness | `scripts/agent_harness.py` | Code block extraction + disk verification |
| Circuit breaker | `graph/supervisor.py` | closed→open→half_open states per agent |
| Config drift | `config/drift/config-drift.yaml` | PEEM feedback → routing constraints (suggest+gate) |
| PEEM evaluation | `graph/evaluation.py` | 6 criteria, dual-judge (NIM3 + Gemini), divergence flag |
| Telegram bridge | `scripts/telegram_bridge.py` | Cross-device dispatch + monitoring |
| Cross-device sync | `scripts/cross_device_sync.py` | Syncthing status + Oracle council fan-out |

---

## 9. Explicit Router — How to Prompt Models Properly

The supervisor uses `router.py find` to get skill/agent matches, then passes them to the triager LLM as context:

```python
# In supervisor.triager_node:
router_context = self._build_router_context(user_input)
# Format: "- [skill:active] build-discipline (score 0.41) — /Users/yegor/.claude/skills/build-discipline/SKILL.md"
# This is injected into the system prompt so the model KNOWS which skills to read
```

**Prompt library flow:**
1. User inputs task → `index_retrieval_node` queries FTS5 index
2. `_build_router_context` calls `router.py find` → returns skill/agent matches with scores
3. Triager LLM receives: index context + router context + available agents/lanes/skills
4. Triager decides: lane, agent, model, skills, project comprehension (vision, market, value exchange, action chain, next step)
5. `dispatcher_node` builds packet with `build_packet()` + `render_system_prompt()`
6. `worker_node` dispatches to agent (CLI via subprocess or NIM via API)
7. `card_writer_node` writes card + verifies claimed files
8. `reviewer_node` evaluates with NIM3 + Gemini judges, stores PEEM scores
9. `_maybe_generate_drift()` → config drift proposals when enough evaluations exist

---

## 10. Immediate Next Actions (This Session)

| # | Action | Command/File |
|---|--------|--------------|
| 1 | Review background test results | Read `sh_1cb1ec03e001twrpRL5mV2eQSM.out` |
| 2 | Test Telegram bridge | `.venv/bin/python scripts/telegram_bridge.py --test` |
| 3 | Test Oracle council fan-out | `.venv/bin/python scripts/cross_device_sync.py --council "<task>"` |
| 4 | Wire agent_harness into supervisor.worker_node | Edit `graph/supervisor.py` |
| 5 | Add explicit dispatch params to `run()` | Edit `graph/supervisor.py` |
| 6 | Add `/api/skills` and `/api/retrieve` endpoints | Edit `api/` + `main.py` |
| 7 | Build Dispatch Cockpit React page | Edit `ui/src/` |
| 8 | Write eval suites (≥20 cases per agent) | `tests/test_eval_*.py` |
| 9 | Dogfood 10 real tasks | `RouterSupervisor().run()` via cockpit |
| 10 | Append retro to vault journal | `~/memory-vault/journals/YYYY-MM-DD.md` |

---

## 11. Definition of "Done" (Project Complete)

- [ ] Dispatch Cockpit UI: lane/model/skill picker + Run button + PEEM result panel
- [ ] All 5 test files pass + new eval tests
- [ ] `make setup` + `make test` work from clean checkout
- [ ] Zero hardcoded `/Users/yegor/` paths (all env vars)
- [ ] PEEM score ≥3.5 average across all judges
- [ ] 10 real dogfood tasks documented with scores + time saved
- [ ] Telegram bridge tested (send + receive)
- [ ] Oracle council fan-out tested (≥1 successful fan-out job)
- [ ] README with setup instructions for new environments
- [ ] Retro entries appended to vault journal for each iteration

---

## 12. Retro Template (Append to vault journal)

```
## Retro — 2026-11-11
### What went well
- NIM key harness built + tested (11 unit tests, 6 live checks)
- Circuit breaker + fallback chains implemented
- Agent harness writes + verifies code blocks
- Oracle VM council live on port 3033

### What went wrong
- (to be filled per iteration)

### What to change
- (to be filled per iteration)

### Next iteration target
- (to be filled per iteration)

🟢 <command that ran>
```

---

**Route:** inline | agent: nim3 | scripts: PRODUCT_SPEC.md, ROWS_ANALYSIS.md, discover_machine.py, supervisor.py, nim_key_harness.py, agent_harness.py, telegram_bridge.py, cross_device_sync.py

🟢 Spec + loop written; Oracle VM council confirmed live (4 models, cap 80); Hermes Nina gateway running; Telegram bridge built but untested; Syncthing process running but API not yet accessible
