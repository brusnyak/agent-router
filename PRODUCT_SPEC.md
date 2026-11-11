# Agent Router — Product Specification

**Version:** 1.0  
**Status:** Draft  
**Owner:** Yegor Brusnyak  
**Last Updated:** 2026-11-11

---

## 1. Vision

A production-grade multi-agent router that routes tasks to the right agent with the right skill, model, and prompt — reliably, fast, and verifiably. It must work unattended, handle failures gracefully, and produce auditable traces for every dispatch.

## 2. Problem Statement

The current router:
- Routes everything to nim3 regardless of task type, even when nim3 lacks tool access (file write, shell)
- Fabricates results (claims file creation that never happened)
- Has no failure recovery, no circuit breakers, no fallback chains
- Judges all output with a single model (nim3), creating single-model bias
- Has no context budget management, no structured state between agents
- Is not open-source ready: hardcoded user paths, no configuration for other environments
- Cannot be trusted as a "router" because it doesn't route — it hardcodes

## 3. Goals

| Goal | Metric |
|------|--------|
| Correct routing | Task → right lane/agent/skill/model with ≥90% accuracy on eval set |
| Verifiable output | Every claimed file creation must be verified on disk; fabricated results = FAIL |
| Failure recovery | Circuit breakers + fallback chains → system always produces *something* |
| Cross-model judging | PEEM scored by ≥2 different model families; divergence flagged |
| Observable | Every agent call logged with trace_id, latency, cost, confidence |
| Fast | P95 dispatch < 60s for unattended tasks |
| Open-source ready | No hardcoded user paths; all paths configurable via env vars |

## 4. Non-Goals

- Multi-user SaaS (single-owner personal router)
- Vector database (SQLite FTS5 is sufficient)
- Real-time WebSocket collaboration
- Mobile app

## 5. System Architecture

### 5.1 Topology: Hierarchical Orchestrator-Subagent (Pattern 3)

```
                    ┌── Subagent A (researcher)
Input → Supervisor ─┼── Subagent B (builder)
                    └── Subagent C (reviewer)
             ↑________feedback_________|
```

**Why:** Tasks require dynamic decomposition; quality control needs a coordinating judgment layer.

### 5.2 Context Architecture

| Strategy | Implementation |
|----------|---------------|
| Structured State Object | RouterState with typed fields, each agent reads/writes only its contract fields |
| Context Budget | Max 8k tokens per agent call; summarize prior steps, don't append full outputs |
| External Memory | kanban.db + cards/*.md packet files as persistent state |
| Checkpointing | After every card write (irreversible side effect) |

### 5.3 Agent Registry

| Agent | Capabilities | Role | Fallback |
|-------|-------------|------|----------|
| nim3 | text-generation | Supervisor / triage / reasoning | nim2 |
| nim2 | text-generation | Worker / execution | nim1 |
| nim1 | text-generation | Worker / rate-limited fallback | deterministic rules |
| claude | text-generation, shell-access, file-write | Build / code / complex reasoning | codex |
| codex | text-generation, shell-access, file-write | Build / code / fix | claude |
| gemini | text-generation, research | Research / deep research | nim2 |
| ecc-code-reviewer | text-generation | Code review / roast | nim3 |
| ecc-agent-evaluator | text-generation | PEEM evaluation | nim3 |
| agency-ui-designer | text-generation | UI design | nim3 |

### 5.4 Capability Model

```
CAPABILITIES = {"text-generation"}  # NIM agents: no tools, no shell
CAPABILITIES = {"text-generation", "shell-access", "file-write"}  # CLI agents
```

Routing enforces: build tasks require `file-write` capability → only CLI agents (claude/codex) eligible, not NIM agents.

### 5.5 Failure Mode Engineering

| Failure Type | Detection | Recovery |
|-------------|-----------|----------|
| Hard failure (error/timeout) | Error code / timeout | Retry with backoff (max 2) → fallback agent → human escalation |
| Silent failure (hallucination) | Evaluator divergence > 1.0 point | Retry with correction prompt → human review |
| Partial failure (truncated output) | Schema validation | Request specific missing fields → regenerate |
| Contradiction (judges disagree) | Score divergence > 1.0 | Arbitration by third judge → human decision |
| Fabrication (file claimed but missing) | Post-dispatch disk verification | Mark card "failed — fabrication", retry with capable agent |
| Loop failure | Iteration counter ≥ 3 | Force exit; escalate with last best output |
| Context failure | Output schema validation failure | Trim context; re-run with compressed state |

**Circuit breaker:** 3 failures in 5 attempts → OPEN state for 60s cooldown → HALF-OPEN test → CLOSED on success.

### 5.6 Human-in-the-Loop Gates

| Gate Word | Action | Timeout | Default |
|-----------|--------|---------|---------|
| send | Blocking approval | 300s | Escalate |
| spend | Blocking approval | 300s | Escalate |
| deploy | Blocking approval | 300s | Escalate |
| push | Blocking approval | 300s | Escalate |
| delete | Blocking approval | 300s | Escalate |
| vault-write | Blocking approval | 300s | Escalate |

### 5.7 Observability

Every agent call emits structured log:
```json
{
  "trace_id": "uuid",
  "span_id": "uuid",
  "agent_id": "...",
  "step": N,
  "latency_ms": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "confidence": 0.0,
  "tools_called": [],
  "errors": [],
  "status": "success|failure|partial|escalated"
}
```

## 6. API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | System health |
| `/api/cards` | GET | List kanban cards |
| `/api/cards/{id}` | GET | Get card detail |
| `/api/cards` | POST | Create card |
| `/api/cards/{id}` | PATCH | Update card |
| `/api/agents` | GET | List available agents |
| `/api/models` | GET | List available models |
| `/api/evaluate/analytics` | GET | PEEM analytics per agent/model |
| `/api/chat` | POST | Dispatch a task (router.run) |
| `/api/approve` | POST | Approve a gated action |

## 7. Evaluation Framework

### Agent-Level Evals (≥20 cases per agent)

| Eval Type | Description |
|-----------|-------------|
| Functional | Does the agent do its job correctly? |
| Instruction adherence | Does it follow system prompt constraints? |
| Schema compliance | Does output match required schema? |
| Confidence calibration | Is stated confidence accurate? |
| Edge case handling | Empty/malformed/out-of-domain input |

### Pipeline-Level Evals

| Eval Type | Description |
|-----------|-------------|
| End-to-end accuracy | Correct final output? |
| Failure recovery | Recovers when one agent fails? |
| Cost compliance | Within token/cost budget? |
| Latency SLA | Completes within acceptable time? |
| Regression | Previously passing cases still pass? |

**Deployment gate:** New version must meet or exceed baseline before shipping.

## 8. Configuration (No Hardcoded Paths)

All paths configurable via environment variables:

| Env Var | Default | Description |
|---------|---------|-------------|
| `AR_PROJECT_ROOT` | `/Users/yegor/Developer/agent-router` | Project root directory |
| `AR_CONFIG_DIR` | `{root}/config` | Config directory |
| `AR_DB_PATH` | `{root}/kanban.db` | SQLite database path |
| `AR_INDEX_DB` | `{config}/index.db` | FTS5 index path |
| `AR_VAULT_PATH` | `/Users/yegor/memory-vault` | Vault directory |
| `AR_VAULT_SANDBOX` | `{vault}/agents` | Agent write sandbox |
| `AR_ECC_PATH` | `/Users/yegor/Developer/ecc-reference` | ECC reference path |
| `AR_ROUTER_PATH` | `/Users/yegor/.agent-skills/router` | Skill+agent router path |
| `AR_NIM_KEY_ENV` | `NIM_3` | Default NIM key env var |

## 9. Open Source Readiness

- [ ] No hardcoded user paths (all via env vars)
- [ ] `requirements.txt` pins all dependencies
- [ ] `make setup` installs everything in one command
- [ ] `make test` runs full test suite (5+ test files)
- [ ] `make lint` runs ruff check + format
- [ ] README with setup instructions for new environments
- [ ] `.env.example` template for required keys
- [ ] CI/CD configuration (GitHub Actions)

## 10. Success Criteria

| Criterion | Threshold |
|-----------|-----------|
| Routing accuracy | ≥90% on eval set |
| Verification rate | 100% of claimed files verified on disk |
| PEEM score | ≥3.5 average across all judges |
| Divergence rate | <0.5 between judges |
| P95 latency | <60s per dispatch |
| Test coverage | All 5 test files pass |
| Zero hardcoded paths | All paths via env vars |

---

*Spec authored using: Multi-Agent Systems Architect (agency), Agentic OS (ECC), Product Manager (awesome-claude-code-subagents)*
