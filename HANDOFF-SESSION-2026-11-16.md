# Session Handoff: Agent Router — 2026-11-16

## Agent router charter — completion status

**State: Horizon 2 wired end-to-end, functional, pushed to GitHub `brusnyak/agent-router` branch `dev/enforcement` (commit `b641052`).**

### What works (verified E2E this session)

| Command | Test | Result |
|---------|------|--------|
| `backbone run "@nim1 <task>"` | NIM via PiWorker | ✅ returns output |
| `backbone run "@nim-chat <task>"` | NIM chat via NimCallWorker | ✅ returns output (bug fixed) |
| `backbone run "@ecc-code-reviewer <task>"` | ECC persona via PersonaWorker | ✅ returns review |
| `backbone catalog ingest` | ECC + agency skill catalog | ✅ 378 skills ingested |
| `backbone rag index-vault` | Vault page indexing | ✅ 50 pages indexed |
| `backbone rag search-vault "<q>"` | Vault search | ✅ BM25 results |
| `backbone workflow <id> <prompt>` | DAG orchestration | ✅ research→write, gate failure skips |
| Oracle `backbone serve --port 8799` | Hub HTTP API | ✅ `/v1/chat/completions` verified through tunnel |
| Mac `backbone node --hub ... --name mac` | Outbound node | ✅ running (PID 883) |
| SSH tunnel `localhost:8799 → oracle-vm:8799` | Bidirectional comms | ✅ "Hello from Oracle!" verified |

### Infrastructure state

**Oracle (HUB):**
- `agent-router.service` active, `backbone.service` active
- `hermes-nina.service` active, `openhands.service` active
- `hermes-mimoza.service` failed (not needed for router)
- Agent-router repo: `/home/ubuntu/agent-router/` — git state unknown (didn't check commit parity with Mac)

**Mac (NODE):**
- `backbone node --hub http://127.0.0.1:8799 --name mac` running (PID 883)
- SSH tunnel to Oracle port 8799 active
- No local backbone daemon (Mac is a node, Oracle is hub) — correct architecture

### Remaining gaps (mitigated, not blockers)

1. **ECC/agency worker CLIs not on PATH** — 15+ worker names referenced in `config/lanes.yaml` (ecc-code-reviewer, agency-ui-designer, ecc-agent-evaluator, jcode, openhands, etc.) have no CLI binary. **Mitigation:** PersonaWorker routes `ecc-*`/`agency-*` specs through NIM chat with persona `.md` context injected. Router reads persona files from `~/Developer/ecc-reference/agents/` (71 files) and `~/.agent-skills/vendor/msitarzewski_agency-agents/` (29 dirs). This works without installing CLIs.

2. **Mac backbone daemon not running** — `backbone daemon` not started on Mac; `submit/daemon` queue mode unavailable. Start with: `backbone daemon --poll 5 --parallel 2`

3. **Git parity between Mac and Oracle** — Mac commit `b641052` pushed; Oracle repo state not verified for parity.

### Code changes this session

- `backbone/workers.py`: Fixed NimCallWorker missing `return` (was implicitly returning `None` on success path); fixed `_chat` to always raise `Transient` instead of returning `Result`
- `backbone/workers.py`: Added PersonaWorker class for ECC/agency persona dispatch
- `backbone/core.py`: Wired PersonaWorker into `__init__` and `_dispatch` for `ecc-*`/`agency-*` specs
- `backbone/cli.py`: Added `workflow`, `catalog`, `rag` subcommands (index-vault, search-vault)
- `backbone/rag.py`: Added `index_vault` + `search_vault` methods; fixed missing `return out` in `search`
- `config/backbone.yaml`: Replaced `/home/ubuntu` hardcoded paths with `~`; fixed goose cmd path
- `HANDOFF.md`: Removed personal references

### Design principle (product, not personal tool)

- No hardcoded user paths — all paths from `__file__`, `~`, or env vars
- Worker resolution is config-driven (`lanes.yaml`, `tiers`, `routes.yaml`)
- ECC/agency personas are data files, not code dependencies — router is agent-agnostic
- KeyPool handles NIM key rotation, cooldown, failover deterministically

---

## Next session — clean start plan

### Phase 0: Verify router parity & health (15 min)
```
cd ~/Developer/agent-router
git pull origin dev/enforcement          # get Mac commits on Oracle
git log --oneline -3                      # confirm parity
python3 -m backbone doctor                # worker usability probe
python3 -m backbone keys                   # NIM key status
```

### Phase 1: AWS setup for Domovyk project #3 (30 min)

AWS region: **eu-north-1** (Stockholm). You mentioned pre-credits (~$100). Steps:

1. Install AWS CLI: `brew install awscli` (Mac) or already on Oracle
2. Configure credentials: `aws configure` → region `eu-north-1`, output `json`
3. Set up Agent Toolkit: follow https://raw.githubusercontent.com/aws/agent-toolkit-for-aws/refs/heads/main/setup-instructions/setup.md
4. Test Domovyk: `cd ~/Developer/domovyk && go run ./cmd/domovyk discover --region eu-north-1 --out inventory.json`
5. Then: `go run ./cmd/domovyk score --inventory inventory.json --out score.json`

CV relevance: Domovyk is a real Go CLI with unit tests, read-only AWS discovery, scoring model. Frame honestly: "v0.0 skeleton, discover/score/price CLI, untested against live AWS until creds added." Do NOT claim production-ready.

### Phase 2: Project #4 research via agent router (autonomous sweeps)

Use the router itself for parallel research:

```
backbone fanout \
  "Research micro-SaaS idea generators and idea validation tools available free in 2026" \
  "Research TrustMRR vertical B2B SaaS niches MRR $1K-$10K little competition" \
  "Research GTM channels for solo-dev micro-SaaS 2026" \
  "Research second brain / AI context layer niche opportunities" \
  --project project-4-research
```

Target: shortlist 3 vertical SaaS niches. Criteria: boring B2B problem, buyer has budget, little competition, solo-dev buildable in ≤2 weeks, path to first paying customer.

### Phase 3: CV & career agent integration

- Check career agent state (career-ops-live repo)
- CV update per mid-level plan (junior headline, four projects, receipts section empty until real receipt)
- Do NOT claim mid-level — vault research explicit: "Mid-level is not reachable by editing the CV"

### Questions / clarifications needed

1. Do you want project-4 research fanout launched now or in the fresh session?
2. Are AWS credentials ready for `~/.aws/credentials` (eu-north-1)?
3. Should Oracle agent-router repo be synced to Mac commit `b641052` before next session?
4. Career agent: check `~/Developer/career-ops-live/` state for job application integration?
