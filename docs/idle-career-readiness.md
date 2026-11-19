# Idle career work: implementation and release gates

Status: NOT ARMED. The idle and career policy modules are offline decision
primitives, not evidence of enforcement. No generic unattended worker may be
enabled merely because these tests pass.

## Intended outcome

After 600 seconds without Mac input, pick a bounded queued career task. Stop
promptly when input resumes, a pause file appears, power or load is unsuitable,
or the supervisor loses its child. Resume safely without double-applying.
Prepare a sourced, qualified job packet and reviewed draft for the owner.

## Release gates

1. **Supervisor**: one process lock shared by all trigger paths; periodic idle,
   power, load and pause checks; hard process-group termination on activity,
   pause, timeout, parent death and termination; bounded retry and durable
   recovery; no partial output marked complete. Prove these with real child
   processes and injected probe failures. Mac sleep/wake is separately tested.
   `backbone/workspace.py:run_group` starts worker processes in a new session:
   killing only the outer router process group does not establish that these
   workers stopped. Require an explicit child-ownership and parent-death design
   and an end-to-end descendant termination test before activation.
2. **Queue**: explicit versioned task schemas and allowlisted handlers, locked
   state, unique idempotency keys, input hashes, atomic output, provenance,
   dependency checks, meaningful per-stage acceptance and failure receipts.
   Changed inputs invalidate downstream artifacts. Never run arbitrary queue
   shell or allow an LLM to expand its own permissions.
3. **Isolation**: no bypass of `BACKBONE_UNATTENDED`; independently demonstrate
   that worker filesystem, credentials, network and browser permissions match
   the task. Prompt-only read-only is insufficient. Restrict external data
   handling and keep sends, applications, account changes, payments and secrets
   outside unattended capabilities.
4. **Career research**: successful collector exit, current employer/official
   posting content, date and source URL, role and region, eligibility including
   work rights and language, and verified application-history deduplication.
   Unknown evidence is HOLD; local DB or HTTP liveness alone is not enough.
5. **Draft and verification**: bind the current single CV hash, job and source
   hashes, exact draft hash, copy-engine results, factual evidence and independent
   review to the packet. A changed draft invalidates review. Worker selection
   requires measured health and task-fit; fallback cannot broaden permissions or
   spend money. A nonempty answer is not a gate.
6. **Application**: owner approval of exact text and action, platform terms,
   candidate-owned essay/declaration requirements and CV attachment version
   precede a one-at-a-time submission. Unattended queue stops at owner review;
   submissions need a separately authorized interactive step and receipt. Any
   uncertain submission outcome is reconciled before retrying.
7. **Operations**: resolve `config_selftest.py` 26/28 failures and run required
   security checks; prove stop behavior, restart recovery and zero unintended
   sends with fixtures, then a bounded observed soak before scheduling.

## Existing evidence and gaps

`career_agent/night_job.py` currently runs its scan with `--live 0`, ignores
collector return codes, uses a fixed night window, and runs outside the router's
unattended mode. It is not a safe task handler for this supervisor. The
`backbone/bracket.py` prototype calls generic `Backbone.run`, which explicitly
rejects unattended operation; its `noop` gate is not a quality check. The
separate `idle_policy.py` and `career_gate.py` modules model decisions only;
their tests do not prove supervisor, browser, isolation or network behavior.
`idle_supervisor.py` is a standalone tested primitive, not an integrated
controller: it does not yet handle parent death or nested worker sessions.

Current worker permissions, providers, authentication, cost and health must be
verified per worker before any OMP, Claude, Antigravity, Kilo, OpenCode or
Cline delegation. The router's picker is a proposal, not verification.
