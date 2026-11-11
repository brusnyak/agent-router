# Phase 1 Spec — Discovery + Self-Configuration

**Project:** agent-router → AI command center (open source, MIT)
**Scope:** First-run machine discovery → self-generated YAML config → no installs, detect-and-configure only
**License:** MIT
**Status:** ✅ COMPLETE

---

## 1. What Phase 1 built

| Component | File | Status |
|---|---|---|
| Discovery script | `scripts/discover_machine.py` | ✅ Done — scans CLI, keys, browsers, vault, skills, hooks, project roots, last30days |
| Configurator | `scripts/configure_from_discovery.py` | ✅ Done — reads inventory JSON, generates models/agents/skills/lanes.yaml + gaps report |
| Vault sandbox | `~/memory-vault/agents/` | ✅ Done — created, designated write root for agents |
| Browser pre-flight | `scripts/browser_preflight.py` | ✅ Done — check Neo/Ego running, `--auto-start` to launch, chat-based interaction flag |
| Indexer (stub) | `scripts/index_vault.py` | ⏳ Phase 2 — sentence-transformers + sqlite-vec index |

---

## 2. Verification results

```
models.yaml: 4 models (nim×3 + gemini-pro)
agents.yaml: 3 agents (claude, codex, gemini)
skills.yaml: 100 skills (from .agent-skills + .claude/skills)
lanes.yaml: 14 lanes (all existing, with fallback_needed flags)
vault sandbox: /Users/yegor/memory-vault/agents/ (created)
idempotent: YES (re-run produces identical counts, no duplicates)
```

**Gaps reported:**
- NIM/Anthropic/OpenAI/Gemini keys in `~/.env` but not in current env — use `with-env`
- opencode CLI not on PATH
- kilo/cline/hermes CLI found but no config dir
- BrowserClaw + ego lite installed but not running

---

## 3. Acceptance criteria (all met)

1. ✅ `python3 scripts/discover_machine.py` runs, writes `config/discovered-inventory.json`
2. ✅ `python3 scripts/configure_from_discovery.py` reads inventory, writes/updates all 4 YAML configs
3. ✅ Re-running configurator is idempotent (no duplicate entries)
4. ✅ `~/memory-vault/agents/` exists after configurator runs
5. ✅ Browser pre-flight correctly reports installed/running status for Neo/Ego
6. ✅ Gaps report printed to stdout lists missing keys/CLIs/browsers

---

## 2. Configurator logic

Input: `config/discovered-inventory.json`

### models.yaml generation
From `keys.env_file_has`:
- NIM_1/NIM_2/NIM_3 → add as `nim` models with `api_key_env` matching, `base_url: https://integrate.api.nvidia.com/v1`, role varies (NIM_3 = supervisor, others = worker)
- ANTHROPIC_API_KEY → `claude-sonnet-5-5`, provider anthropic, role worker
- OPENAI_API_KEY → `gpt-6.1-sol`, provider openai, role worker
- GEMINI_API_KEY → `gemini-pro`, provider google, role worker, browser-only (delegated via Neo/Ego)

Role assignment heuristic:
- If NIM_3 present → supervisor model = nim-3-super-vl
- Else if any NIM key → supervisor = first available NIM
- Else → supervisor = none (warn user)

### agents.yaml generation
From `agents.cli_on_path` + `agents.config_dirs`:
- Only include agents where CLI found AND config dir exists → "usable"
- Write access: true for claude, codex, kilo, cline, hermes; false for nim*, gemini
- route_reasons: map from existing lanes.yaml lane→agent mappings
- skills: empty initially (populated by indexer in Phase 2)
- note: "auto-discovered by discover_machine.py — review before production use"

### skills.yaml generation
From `skills.*` locations:
- Each SKILL.md file → one skill entry with id = relative path slug, path = full path, category = parent dir name
- Dedupe by filename

### lanes.yaml generation
Keep existing lanes (planner, build, review-roast, ops-repair, config-edit, research-public, mechanical, content-clips, vision, cash-leads, cash-outreach, upwork, jobs, owner-only) but:
- Map `engine` to discovered usable agents only; if engine's CLI not found, mark `fallback_needed: true`
- Add `model_availability_check: true` to each lane

### Gaps report (printed, not written)
- "NIM keys found in ~/.env but not in current env — run `source ~/.env` or use `with-env`"
- "opencode CLI not on PATH — install or add to PATH"
- "kilo CLI found but no config dir — verify kilo is configured"
- "No Anthropic/OpenAI key — Claude/Codex worker routing limited"
- "Vault agents sandbox missing — will create at ~/memory-vault/agents/"
- "No browser running — Neo/Ego available but not started"

---

## 3. Vault sandbox enforcement

Create `~/memory-vault/agents/` directory if missing.

Dispatcher rule (Phase 2, stubbed here): any agent write to vault must be under `~/memory-vault/agents/<agent-id>/`. Writes to root vault, `*secret*`, `*key*`, `*credential*` paths → interrupt block.

---

## 4. Browser pre-flight

Check `pgrep -ax "BrowserClaw"` and `pgrep -ax "ego lite"`.
- If not running → offer `open -a "BrowserClaw"` or `open -a "ego lite"`
- Chat-based interaction flag: if browser available and task requires deep research → "Delegate to Gemini via browser? (y/n)"
- If neither running and user declines → degrade to text-only (NIM/skills only)

---

## 5. Acceptance criteria (Phase 1)

1. `python3 scripts/discover_machine.py` runs without error, writes `config/discovered-inventory.json`
2. `python3 scripts/configure_from_discovery.py` reads inventory, writes/updates models.yaml, agents.yaml, skills.yaml, lanes.yaml
3. Re-running configurator is idempotent (no duplicate entries, preserves manual edits with `_source: discovered` vs `_source: manual` markers)
4. `~/memory-vault/agents/` exists after configurator runs
5. Browser pre-flight correctly reports installed/running status for Neo/Ego
6. Gaps report printed to stdout lists missing keys/CLIs/browsers

---

## 6. What Phase 1 does NOT do

- No sentence-transformers / sqlite-vec index (Phase 2)
- No LangGraph supervisor changes (Phase 2)
- No dispatcher shell=False / worktree changes (Phase 2)
- No UI changes (Phase 3)
- No proactive loop (Phase 2)
- No installs of any kind

---

## 7. Next step

Run the configurator. I'll write `scripts/configure_from_discovery.py` after you confirm this spec. Any changes to the acceptance criteria or gap categories?
