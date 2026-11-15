# Orchestration options review — Oracle + Orca (2026-11-15)

Reviewed by a read-only subagent. Every claim below is from a command run this session unless marked `unverified:`.

## 0. Verified environment facts

| Fact | Source (command) | Result |
|---|---|---|
| Oracle reachable | `ssh oracle-vm` | public IP 84.8.249.139 works; **Tailscale IP 100.126.90.86 SSH times out** |
| Oracle shape | `ssh oracle-vm 'uname -m; nproc; free -g'` | aarch64, 2 CPU, 11GB RAM (9GB available) |
| goose 1.59.1 on Oracle | `~/bin/goose --version` | OK; **not on PATH** (`PATH` lacks `~/bin`) |
| goose + NIM on Oracle | `goose run --no-session --max-turns 2 -t "reply with exactly: GOOSE_ORACLE_OK"` | `GOOSE_ORACLE_OK` (NIM_2). **Required writing `~/.config/goose/config.yaml`** (did not exist → "no provider configured") |
| jcode on Oracle | `jcode v0.99.1`, `jcode run -p nvidia-nim -m nvidia/nemotron-3.5-super-vl-120b-a12b --json …` | `ORACLE_JCODE_OK`, 17549 in / 24 out tokens. Binary installed at `~/bin/jcode` (from `jcode-linux-aarch64.tar.gz`, v0.99.1) |
| pi on Oracle | `~/agent-router/.tools/pi -p --model nim1/…` | `ORACLE_PI_OK`. Binary at `~/.local/bin/pi`, symlinked from `~/agent-router/.tools/pi`; **not on PATH** |
| Orca on Oracle | `ps`, `which orca`, `ss -tlnp` | **no Orca binary, no runtime process, no listener** |
| Orca environment | `orca environment list` | `8deac4bf-… oracle-vm ws://127.0.0.1:60788/` — registered but **dead**: no tunnel on Mac (`curl 127.0.0.1:60788` → 000), no server on Oracle |
| Oracle services | `systemctl list-units` | council / queue-events / research-events (hermes) + oauth2-proxy + tailscaled. **No backbone unit** |
| Oracle custom UI | `ss -tlnp` | `127.0.0.1:8799` python pid 620493 — alive; Mac tunnel pid 28772 forwards to it |
| jcode Linux ARM64 exists | GitHub release v0.99.1 assets | `jcode-linux-aarch64.tar.gz` ✅ (CI only builds x86_64 linux, but the asset is published) |

## 1. Oracle worker recommendation

**Primary: goose. Secondary: jcode. Tertiary: pi.**

- **goose** — KeyPool failover native (`GooseWorker.run → pool.call`), token-cheap, verified end-to-end on Oracle today, and it is the only candidate that exposes **ACP over HTTP** (`goose serve`, 127.0.0.1:3284) — the hook the custom UI needs.
- **jcode** — the right tool for *fan-out inside one task*: native **Swarm** (agents spawn subagents, DM/broadcast, file-shift conflict detection), 56 MB static binary, RAM-light (claimed 71.3 MB first session / ~3.3 MB per extra session; **claim not tested here**). Costs ~17.5k input tokens per call on Oracle (29k measured on Mac).
- **pi** — fastest on the owner's own bench (11/18/15 s vs jcode 24/30/35 s), KeyPool-native, already on Oracle. No native swarm, ~79.6 MB RAM per extra session.

**Correction to the "jcode is much faster" claim.** Upstream's numbers are **time-to-first-input** (19.1 ms vs pi 596 ms) and **RAM per session**, not task throughput. On the owner's own `docs/BENCH-2026-11-15.md`, jcode was the *slowest* NIM worker (24/30/35 s) and cost ~29k input tokens per call. jcode is faster to start and cheaper in RAM; it is not faster to finish.

## 2. Top 3 Oracle alternatives to goose (from the 39-list)

1. **jcode** (`1jehuang/jcode`, YC S26, MIT) — verified on Oracle ARM64. `jcode run --json -p nvidia-nim -m <model> <prompt>`. Providers: `nvidia-nim`, `openrouter`, `openai-compatible`. Native swarm. Needs `NVIDIA_API_KEY` env or `~/.config/jcode/nvidia-nim.env`. Telemetry on by default → `JCODE_NO_TELEMETRY=1`.
2. **pi** — verified on Oracle. `--model nim<N>/<model>` multi-key, KeyPool-native, fastest. Downside: 24× jcode's per-session RAM, no swarm.
3. **crush** (Charm, FSL-1.1-MIT) — Go static binary, `crush-0.101.0_aarch64.deb`/`.apk`/`.rpm` published. `crush run -q -m provider/model "<task>"` is genuinely headless and **auto-approves every permission** in non-interactive mode. Supports OpenAI-compatible + Anthropic-compatible endpoints (so a NIM base URL works) and OpenRouter natively. Weakness: no documented JSON output → harder for backbone to parse; needs a `crush.json` provider block.

**AMP verdict: 4th, conditional.** Headless is real (`amp -x`, `--stream-json`, `--json`), but it is a **closed hosted product**: auth needs a paid `AMP_API_KEY` (`sgamp_…`), there is **no custom base URL**, so NIM is impossible — only OpenRouter BYOK or Amp's own catalog. Amp also **runs tools with no approval prompt**, so it needs isolation the other three do not.

Rejected for Oracle: **opencode** (0/3 gate pass on first run, wrote into the main repo instead of the worktree, 49–113 s, 637 MB); **aider** (pip on ARM64, OpenRouter only, slow, no swarm); **agy/gemini/qwen** (Google/Alibaba quota, not NIM); **cursor/droid/devin/kimi** (hosted accounts).

## 3. Orca-side replacement for OpenCode

**Use Orca's own agent launch + worktree/automation layer, not OpenCode.**

- Oracle is already a registered Orca environment (`oracle-vm`) — so Orca→Oracle launch is the intended path, **but the runtime is missing** (see blockers).
- `orca agent launch --agent <id> --environment oracle-vm --worktree <sel> --prompt <text> --model <id> --effort <level> --surface terminal` is the native primitive.
- Orca's **managed-account agents are claude, codex, opencode, devin** (`orca account add --agent …`). Orca also has provider-usage integrations for gemini, grok, cursor, zcode, antigravity, and a **jcode hook** (`~/.orca/agent-hooks/jcode-hook.sh`) — jcode is a first-class Orca-known agent.
- Orchestration primitives Orca already owns: `orca worktree ps` (cross-worktree orchestration summary), `orca worktree create --agent`, `orca automations create/run`, `orca terminal wait`, `orca vm recipe doctor`, `orca project setup-*`. These replace the need for OpenCode's 24 in-process subagents for fan-out.
- The `orchestration` skill (Orca workers: research/build/review/verify/browser/handoff) already dispatches Codex/Claude workers through `orca-cli` — that is the Orca-native orchestrator, and it does not touch OpenCode.

**Recommendation:** default Orca agent = **claude** (managed account) for interactive/review work; **jcode** on Oracle for cheap NIM bulk work; keep OpenCode only as a fallback for the 24 named subagent personas until they are ported to Orca workers.

## 4. Multi-key NIM rotation — assessment

**Partially effective. Two real holes.**

What is true:
- `backbone/keys.py` `KeyPool` round-robins NIM_1/2/3: `_rr` cursor, ordered by (cooling → avoided → fewest in-flight → fewest in-window). Cooldown on 429 via `Retry-After`. Every key gets a chance (`attempts = max(retries+1, len(names))`).
- `rpm_limit` is **40** per key per 60 s (both `config/backbone.yaml` and `~/.agent-router/backbone.yaml`). The "30 RPM soft / 40 hard" note in `orchestration-state.md` does not match the code — there is one value, 40.
- Only **pi** and **goose** go through the pool (`pool.call`).

The holes:
1. **The window counts leases, not requests.** `lease()` appends to `_win[n]` once per agent run and holds the key for the whole run. A `goose run --max-turns 10` makes 10+ HTTP requests but is counted as 1. So the pool bounds *concurrent agent runs per key*, **not request rate against NIM**. A single run can still burst a key.
2. **`JcodeWorker` bypasses the pool entirely.** Its signature is `run(self, prompt, cwd, key: str = "NIM_1", token: str = "", …)` and it reads `os.environ.get(key)` — always NIM_1 unless a caller passes another. `ClineWorker` is the same shape. `OpencodeWorker` also takes a fixed `key` (default NIM_1) and only switches the nim_proxy slot.
3. **`nim_proxy.py` does not rotate.** `/nim1→NIM_1`, `/nim2→NIM_2`, `/nim3→NIM_3`, 1:1, no failover, no cooldown, no rate limit. The caller picks the slot.

**Answer to "does this prevent single-key spam": no.** It prevents one *run* from monopolising a key across the roster, and it gives pi/goose failover across keys — but jcode is pinned to NIM_1, and no layer caps requests-per-key inside a run.

Smallest fixes: give `JcodeWorker` the same `pool.call` shape as `GooseWorker`; count requests (not leases) per key, or lower `rpm_limit` to match the real NIM quota; make `nim_proxy` fail over on 429 to the next key.

## 5. Backbone state — live bugs found

**A. Two backbone copies on Oracle, opposite resolution behaviour.**
- Canonical per `hosts.oracle-vm.dir`: `~/agent-router` (has `.tools/pi` → `~/.local/bin/pi`).
- Also present: `~/Developer/agent-router` (**no `.tools/`**).
- `_resolve()` derives the fallback from `__file__`. Measured:
  - from `~/agent-router` → `resolve(pi) = ['/home/ubuntu/agent-router/.tools/pi']` ✅
  - from `~/Developer/agent-router` → `resolve(pi) = ['pi']` ❌ (pi is not on PATH; `PATH` has no `~/.local/bin`)
  - `resolve(goose) = ['goose']` ❌ (goose is not on PATH; `PATH` has no `~/bin`)
- So pi on Oracle works **only** when backbone runs from `~/agent-router`, and goose works from nowhere until PATH or the cmd path is fixed.

**B. Oracle `~/.agent-router/backbone.yaml` has NO goose entry.** Its `workers:` block is only `pi: {cmd: pi, timeout_s: 600}`. The briefing said "Oracle backbone.yaml still says `cmd: goose`" — that is wrong; there is no goose key at all. The Mac override `~/.agent-router/backbone.yaml` does have `goose: {cmd: goose, timeout_s: 600}`.

**C. Backbone never runs on Oracle.** No systemd unit; only hermes council/queue/research + oauth2-proxy + tailscaled. Oracle is source-only.

**D. Goose on Oracle had no provider config.** `~/.config/goose/` did not exist → goose would fail with "no provider configured". Written during this review:
```yaml
GOOSE_TELEMETRY_ENABLED: false
GOOSE_MODE: auto
active_provider: nvidia
providers:
  nvidia: {enabled: true, model: nvidia/nemotron-3.5-super-vl-120b-a12b, configured: true}
```

## 6. Who orchestrates Oracle workers

**Backbone orchestrates; Oracle stays an execution host. jcode does intra-task swarm on Oracle. Orca is the human-facing control plane.**

- Backbone already owns the KeyPool, the bandit, the reviewer/supervisor, the run DB and workspace isolation (`data/work/<id>`). Oracle has neither a backbone service nor an Orca runtime, so neither can be the top-level scheduler today.
- Oracle has 2 OCPU / 9 GB free — pull-based fan-out from Mac-side backbone beats a resident orchestrator on the VM.
- **Do not run two orchestrators over the same workers.** Backbone = cross-harness fan-out (pi / goose / jcode across keys). jcode's native swarm = sub-agent fan-out *inside* one task. Orca = interactive launch + `worktree ps` + automations for the human.
- Key placement: the key must reach Oracle for jcode/goose (Oracle `~/.env` already holds NIM_1/2/3). If that is unacceptable, terminate NIM through the Mac-side `nim_proxy` and point the Oracle worker at it over the existing tunnel instead of shipping keys to the VM.

## 7. Immediate next steps

Oracle:
1. `goose`: add `~/bin` to PATH (systemd `Environment=` / `~/.profile`) **or** set `cmd: /home/ubuntu/bin/goose` in `~/.agent-router/backbone.yaml`.
2. `~/.agent-router/backbone.yaml`: add `goose: {cmd: /home/ubuntu/bin/goose, timeout_s: 600}` and `jcode: {cmd: /home/ubuntu/bin/jcode, timeout_s: 600}` (installed and verified as `~/bin/jcode`).
3. Pick **one** backbone copy on Oracle and delete or symlink the other, so `_resolve()` cannot pick the `.tools`-less tree.
4. `JcodeWorker` → route through `KeyPool` like `GooseWorker` (code change in `backbone/workers.py`).
5. Decide whether backbone gets a systemd unit on Oracle or stays manual/SSH-driven from Mac.

Mac:
6. Mirror the goose+jcode worker entries into `~/.agent-router/backbone.yaml` (the Mac override is what actually runs).
7. Either install `orca serve` on Oracle and re-pair the `oracle-vm` environment (restore the 60788 tunnel), or `orca environment rm oracle-vm` so the dead entry stops lying.
8. Re-check `docs/BENCH-2026-11-15.md` with jcode on Oracle: the bench has never measured jcode headless RAM on this VM ("parallel RAM claim not tested").

## 8. Blockers / questions

1. **Which backbone copy is canonical on Oracle** — `~/agent-router` or `~/Developer/agent-router`? The pi resolve bug depends on it.
2. **Tailscale SSH is not working.** `ssh ubuntu@100.126.90.86` times out; only `ssh oracle-vm` (public 84.8.249.139) works. The briefing said Tailscale was reachable — it is not, for SSH. Was Tailscale supposed to replace the public IP?
3. **Orca↔Oracle runtime is missing.** Environment is registered, server is not installed, tunnel is not up. Install `orca serve` on Oracle + re-pair, or drop it?
4. **May NIM keys live on the VM?** Oracle `~/.env` already holds NIM_1/2/3 — confirm that is intended and not a leak.
5. **30 vs 40 RPM** — which is the intended cap? And should the cap count requests rather than runs?

## 9. Weakest point in this review

The single-sample comparison is the weakest link: one `ORACLE_*_OK` per worker, one task class, no repeated runs, no concurrency measurement. jcode's RAM advantage (the whole reason to prefer it) is **still unmeasured on this VM** — upstream's number is a different machine. Until `bench_headless_memory.py` runs on Oracle with 3–4 concurrent jcode sessions, jcode's fit for the 2-OCPU box is a claim, not a measurement.
