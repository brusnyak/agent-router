# Agent Router — Rows Analysis (Remaining Work)

**Date:** 2026-11-11  
**Purpose:** Decision matrix for what remains to make agent-router production-ready and open-source releasable  
**Method:** Severity (1-5) × Effort (1-5) = Priority score. Higher = do first.

---

## Scoring Key

| Severity | Meaning |
|----------|---------|
| 5 | Blocks dogfood / open-source release; data loss or silent failure risk |
| 4 | Major reliability gap; produces incorrect results without detection |
| 3 | Moderate gap; works but needs improvement for production |
| 2 | Minor polish; nice to have |
| 1 | Cosmetic |

| Effort | Meaning |
|--------|---------|
| 1 | < 1 hour, trivial change |
| 2 | 1-4 hours, small refactor |
| 3 | 1-2 days, moderate implementation |
| 4 | 3-5 days, significant feature |
| 5 | 1+ week, major subsystem |

---

## Rows Table

| # | Gap | Sev | Effort | Score | Dependencies | ECC Reference | Status | Blocks OSS? |
|---|-----|-----|--------|-------|-------------|---------------|--------|-------------|
| 1 | NIM agent fabrication: nim2/nim3 generate code but can't write files; harness now writes code blocks but not integrated into supervisor | 5 | 2 | **10** | agent_harness.py, card_writer_node | agentic-os (file-based state), multi-agent-architect (trust & permission) | In progress | **Yes** |
| 2 | No NIM API key harness (rotation + retry + backoff) — naive single-key checks, no 429 handling | 4 | 2 | **8** | agent_harness._nim_call | agentic-os (cost tracking) | Not started | **Yes** |
| 3 | Circuit breaker HALF_OPEN transitions missing — no reset-on-success in half_open | 4 | 1 | **4** | supervisor._cb_record_success/failure | multi-agent-architect (circuit breaker pattern) | Partially done | No |
| 4 | claimed_files regex still has edge cases — fixed to require extensions, needs more testing | 3 | 1 | **3** | agent_harness.extract_claimed_files | anti-slop (design tells) | Done | No |
| 5 | No structured observability — trace_id exists but not emitted as structured logs per agent call | 4 | 3 | **12** | supervisor.worker_node trace_log | multi-agent-architect (observability) | Partially done | **Yes** |
| 6 | No context budget management — no max tokens per agent, no summarization | 3 | 3 | **9** | supervisor.triager_node, state.py | agentic-os (context budget) | Not started | No |
| 7 | No eval suites per agent (≥20 cases) — no baseline, no regression detection | 4 | 4 | **16** | evaluation.py, tests/ | multi-agent-architect (eval-driven development) | Not started | **Yes** |
| 8 | No HITL interface — interrupt exists but no approve/reject/modify UI with reasoning trace | 4 | 3 | **12** | api/chat.py, ui/ | multi-agent-architect (HITL gate design) | Not started | **Yes** |
| 9 | No code execution sandbox — worktree isolation exists but claude/codex TTY issues prevent dispatch | 5 | 4 | **20** | agent_base.CLIAgent, _dispatch_cli | multi-agent-architect (sandboxing) | Blocked | **Yes** |
| 10 | Frontend UI lacks PEEM scorecards, agent comparison, design-critic gate | 3 | 4 | **12** | ui/src/, DESIGN.md | design-critic, design-sop | Not started | No |
| 11 | Open-source config: hardcoded user paths remain in some places | 3 | 2 | **6** | discover_machine.py, supervisor.py | agentic-os (declarative config) | Partially done | **Yes** |
| 12 | ECC skills discovered but not wired into triager routing | 3 | 2 | **6** | supervisor._build_router_context | multi-agent-architect (agent specialization) | Partially done | No |
| 13 | Agency agents not usable (claude/codex TTY issues) — same as #9 | 5 | 4 | **20** | agent_base.CLIAgent | multi-agent-architect (tool access matrix) | Blocked | **Yes** |
| 14 | Cross-device sync (Syncthing/Oracle VM council) unverified | 2 | 2 | **4** | cross_device_sync.py | agentic-os (external memory) | Not started | No |
| 15 | Telegram bridge unconnected (credentials in .env but never tested) | 2 | 1 | **2** | telegram_bridge.py | agentic-os (notifications) | Not started | No |

---

## Priority Order (by Score)

| Priority | # | Gap | Score | Next Action |
|----------|---|-----|-------|-------------|
| P0 | 9 | Code execution sandbox (TTY fix for claude/codex) | 20 | Fix `script` wrapper or use `pty` module; test codex dispatch |
| P0 | 13 | Agency agents usable | 20 | Same as #9 — unblocks agency-ui-designer, ecc-code-reviewer etc. |
| P0 | 1 | NIM agent fabrication integrated into supervisor | 10 | Wire agent_harness.py into supervisor.worker_node + card_writer_node |
| P0 | 7 | Eval suites per agent | 16 | Write ≥20 test cases per agent; baseline scores |
| P0 | 2 | NIM API key harness | 8 | Extract _nim_call into nim_key_harness.py with rotation + backoff |
| P1 | 5 | Structured observability | 12 | Emit trace_log entries as JSON lines to file |
| P1 | 8 | HITL interface | 12 | Add /api/approve endpoint; UI approve/reject buttons |
| P1 | 6 | Context budget management | 9 | Add token counting + summarization in triager |
| P1 | 10 | Frontend PEEM scorecards | 12 | Build PEEM Scorecard React component |
| P2 | 3 | Circuit breaker HALF_OPEN | 4 | Add reset-on-success / trip-on-failure in half_open |
| P2 | 4 | claimed_files regex testing | 3 | Add unit tests for edge cases |
| P2 | 11 | Open-source config paths | 6 | Replace remaining hardcoded paths with env vars |
| P2 | 12 | ECC skills in triager | 6 | Wire router.py matches into lane/agent selection |
| P3 | 14 | Cross-device sync | 4 | Run cross_device_sync.py --status |
| P3 | 15 | Telegram bridge | 2 | Run telegram_bridge.py --test |

---

## What "Done" Looks Like (Open-Source Ready)

All P0 and P1 items complete:
- [ ] Code execution sandbox works (claude/codex dispatch via TTY or pty)
- [ ] NIM agent fabrication eliminated (harness writes + verifies code)
- [ ] Eval suites exist (≥20 cases per agent, baseline recorded)
- [ ] NIM API key harness with rotation + backoff
- [ ] Structured observability (trace_id per agent call, JSON lines)
- [ ] HITL interface (approve/reject/modify with reasoning trace)
- [ ] Context budget management (max tokens + summarization)
- [ ] Frontend PEEM scorecards + agent comparison
- [ ] All paths configurable via env vars (no hardcoded /Users/yegor/...)
- [ ] All 5 test files pass + new harness tests

---

## What's Already Working (Don't Touch)

- NIM agent dispatch via API (nim1/nim2/nim3) — ~1 second per task
- Code block extraction + file writing + verification (agent_harness.py)
- Circuit breaker with closed→open→half_open transitions
- Router self-discovery via router.py (1,055 items indexed)
- Dual-judge PEEM evaluation (NIM3 + Gemini API)
- Config drift from PEEM feedback
- Post-dispatch file verification (anti-fabrication)
- Project .env loading (not global env)
- All paths configurable via env vars (discover_machine.py, supervisor.py)

---

## Next Immediate Actions (This Session)

1. **Fix code execution sandbox** — get claude/codex dispatching (pty module or fix `script` wrapper). This unblocks agency agents + build lane.
2. **Integrate agent_harness.py into supervisor.py** — replace worker_node dispatch with harness.run() so all dispatch goes through verification.
3. **Write eval suites** — 20 cases per agent (nim3, nim2, codex, claude).
4. **Add NIM key harness** — extract _nim_call into standalone module with rotation + backoff.

---

## Notes

- NIM2 and NIM3 both work (~1s per task) but were temporarily rate-limited earlier — key rotation handles this
- Codex CLI needs TTY (script wrapper partially works but outputs ANSI codes) — needs pty module
- Claude CLI untested (no Anthropic API key) but binary exists at /Users/yegor/.local/bin/claude
- The harness is the critical path: it turns NIM from "text generator" into "reliable code executor" by writing + verifying code blocks
