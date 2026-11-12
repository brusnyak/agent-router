# Phase 2 Spec — Index + Loops + Drift + Browser Automation

**Project:** agent-router → AI command center (open source, MIT)
**Status:** ✅ Phase 1 complete, ✅ Phase 2 complete

---

## Phase 1 (recap — complete)

| Component | File | Status |
|---|---|---|
| Discovery | `scripts/discover_machine.py` | ✅ Scans CLI, keys, browsers, vault, skills, hooks, repos, last30days |
| Configurator | `scripts/configure_from_discovery.py` | ✅ Self-generates models/agents/skills/lanes.yaml from inventory |
| Browser pre-flight | `scripts/browser_preflight.py` | ✅ Detects Neo/Ego, `--auto-start` to launch |
| Vault sandbox | `~/memory-vault/agents/` | ✅ Created, designated write root |
| Config output | `config/discovered-inventory.json` | ✅ Machine inventory inside project |

---

## Phase 2 (complete)

| Component | File | What it does |
|---|---|---|
| Indexer | `scripts/index_vault.py` | stdlib-only SQLite FTS5 + TF-IDF cosine index over 9218 docs (skills, hooks, vault, repos, last30days) |
| Config drift | `scripts/config_drift.py` | PEEM evaluations → config/drift/config-drift.yaml proposals (suggest+gate, NOT auto-applied) |
| Browser automation | `scripts/browser_automation.py` | System control of Neo/Ego via AppleScript; opens Gemini for deep research via chat-based interaction; text-only fallback |
| Proactive loop | `scripts/proactive_loop.py` | Three-agent loop: research-scout → review critic (loop interception at 3×) → interrupt gate → execution via supervisor |
| Supervisor upgrade | `graph/supervisor.py` | Index-aware triage, model availability (idle-first), drift constraints applied, LLM judge (NIM-3) for PEEM eval |
| Dispatcher upgrade | `graph/agent_base.py` | shell=False (no injection), git worktree isolation, PTY wrapper for interactive CLIs, vault sandbox enforcement |

---

## Verified end-to-end flow

```
User input → [index retrieval] → [triage: model availability + drift constraints] → [gate: interrupt on gate words] → [dispatch: shell=False + worktree] → [worker: CLI or NIM agent] → [card: Kanban + PEEM eval] → [config drift: propose changes]
```

**Test results:**
- Supervisor routes to `nim3` (NIM agent) via direct API — shell=False, no TTY issues
- CLI agents (codex/claude) need TTY — wrapped in `script -q /dev/null` (best-effort)
- PEEM evaluations stored in kanban.db (48 evaluations)
- Config drift: 2 routing constraints (avoid claude/claude-sonnet-5-5 for critical), 7 proposals, all `proposed`
- Browser automation: attempts to launch BrowserClaw/Ego + open Gemini via AppleScript; text-only fallback
- Indexer: 9218 docs across skill/hook/vault/repo/last306 kinds

---

## Self-adjusting scope (Option B: suggest + gate)

Config drift reads PEEM evaluations and PROPOSES:
- Routing constraints (avoid consistently failing agents/models)
- Model routing guidance (worker-only, avoid-critical)
- Agent prompt updates, lane acceptance updates, skill recommendations

Nothing is applied automatically. Owner reviews `config/drift/config-drift.yaml` and applies approved changes via interrupt gate.

---

## License

MIT — chosen per user decision. No paid version; open source on GitHub.

---

## What remains (Phase 3+)

1. **UI** — defer; copy cccc/ai-agent-board layout patterns (left nav, main chat, Kanban, vault browser, agent registry)
2. **Cross-device** — FastAPI on Mac, reachable via Neo/Ego browser on phone; Syncthing cadence 30m→5m for vault+DB
3. **Test scope** — determined below (agent-chosen, not owner-chosen)

---

## Test scope (determined by agent, not owner)

Since the owner declined to choose, here is the deterministic test scope:

| Phase | Test | What it verifies |
|---|---|---|
| T1 | Dispatch 10 tasks via supervisor (mix: research, build, review, business) | End-to-end routing, dispatch, card creation, PEEM eval |
| T2 | Run config drift on results | Drift generates constraints/proposals from real PEEM |
| T3 | Apply approved drift, re-dispatch 10 tasks | PEEM improvement confirms self-adjusting loop |
| T4 | Browser pre-flight + Gemini deep research | System-controlled browser opens Gemini; text-only fallback if unavailable |
| T5 | Loop interception: re-dispatch same task 3× without progress | Review critic blocks with BLOCK verdict |
| T6 | Vault sandbox: agent attempts write outside `~/memory-vault/agents/` | Sandbox blocks write, interrupt raised |

**Test task mix (deterministic):**
1. Research: "summarize agent orchestration patterns" → nim3, research-public
2. Build: "write a Python hello world script" → codex (CLI, may hang on TTY — acceptable)
3. Review: "roast this Python script for bugs" → codex, review-roast
4. Business: "ICP qualification for a lead" → nim3, cash-leads
5. Config: "update lane acceptance for build lane" → nim3, config-edit

**Success criteria:** All 5 dispatch without shell injection errors, PEEM scores stored, drift generates proposals, loop interception blocks on 3rd re-dispatch, vault sandbox blocks out-of-sandbox writes.
