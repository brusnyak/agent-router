# Architecture

Five views of the system. Everything on the prompt path is shadow only: it records, it does not inject. State is as of 2026-11-13 (`HANDOFF.md`).

## 1. System

A dictated prompt reaches Claude Code, which fires the shadow hook (`backbone/hook.py`). The hook appends a receipt to `~/.agent-router/hook-shadow.jsonl`. A PostToolUse hook (`scripts/outcome_hook.py`) records Skill, Agent and Task calls. Offline, `scripts/nightly.sh` rebuilds the catalog, enriches receipts with NIM embeddings, runs the librarian and writes the report.

```mermaid
flowchart LR
    A["Dictation"] --> B["Claude Code session"]
    B --> C["Shadow hook"]
    C --> D["Receipts jsonl"]
    B --> E["PostToolUse outcome hook"]
    E --> F["Outcome rows"]
    G["Nightly script"] --> H["Build catalog"]
    H --> I["Enrich with NIM embeddings"]
    D --> I
    I --> J["Enriched receipts"]
    H --> K["Librarian"]
    K --> L["Proposal report in research"]
    J --> M["Treat vs holdout report"]
    F --> M
```

## 2. One prompt

The hook assigns an arm from the session id: FNV-1a of the id modulo 100, below 20 is `holdout`, otherwise `treat`. Both arms behave identically in v0 because nothing is injected; the arm exists so the A/A check can prove the pipeline has no bias before live injection. Machine turns, lane children and short prompts bypass with no arm. The hook is wrapped to fail open.

```mermaid
sequenceDiagram
    participant U as Owner
    participant C as Claude Code
    participant H as hook.py
    participant L as Receipt log
    participant O as outcome_hook.py
    U->>C: dictated prompt
    C->>H: UserPromptSubmit payload
    H->>H: bypass checks
    H->>H: arm = FNV-1a of session id mod 100 under 20 is holdout
    H->>L: append hash, length, arm, ids
    H-->>C: empty stdout, exit 0
    C->>C: model works on the unmodified prompt
    C->>O: PostToolUse for Skill, Agent or Task
    O->>L: append outcome row
```

## 3. Evaluation pipeline

Transcripts under `~/.claude/projects` are mined for prompts. 310 of 1,321 were relayed subagent messages and are dropped, leaving 1,011. Three LLM judges label each; where two agree the label is silver (517 of 1,011). Baselines are scored against silver, and a result counts only if it passes its gate in `docs/MVP-2026-11-13.md`. Silver is unverified, hence the owner spot-check gate.

```mermaid
flowchart TD
    A["Claude transcripts"] --> B["Mine prompts"]
    B --> C["Drop relayed subagent messages"]
    C --> D["1011 prompts"]
    D --> E["Judge one"]
    D --> F["Judge two"]
    D --> G["Judge three"]
    E --> H["Two of three agree"]
    F --> H
    G --> H
    H --> I["Silver labels 517"]
    I --> J["Baselines lexical dense router"]
    J --> K["Compiler test"]
    K --> L["Gates"]
    I --> M["Owner spot check"]
    M --> L
    L --> N["Ship or stay shadow"]
```

## 4. Worker dispatch

`backbone run` takes `[/command] [#project] [@worker] prompt`. The task is copied into an isolated workspace, which sees only committed files; `--no-isolate` runs in place and is needed for uncommitted work. Workers that `backbone doctor` marked unusable (`data/doctor.json`, read by `backbone/health.py`) are skipped. A gate command checks the result. Two failed attempts escalate to the expert worker; `--escalate ''` disables that.

```mermaid
stateDiagram-v2
    [*] --> Run: "backbone run"
    Run --> Isolate: "default"
    Run --> Worker: "no-isolate"
    Isolate --> Worker: "copy of committed files"
    Worker --> Gate: "patch or answer"
    Worker --> Skip: "doctor marks worker unusable"
    Skip --> Worker: "next worker in tier"
    Gate --> Done: "gate passes"
    Gate --> Worker: "retry once"
    Gate --> Escalate: "two failures"
    Escalate --> Done: "expert passes"
    Escalate --> Blocked: "disabled or fails"
    Done --> [*]
    Blocked --> [*]
```

## 5. Topology

Oracle is the always-on hub; the Mac is the dev machine and a node. The node connects outbound only, through an `ssh -L` tunnel to the hub's loopback port 8799; nothing on the Mac listens for Oracle. Hooks, transcripts, receipts and held-out data stay on the Mac. Any chat or agent front end can talk to `backbone serve` over its OpenAI-compatible HTTP API. Hub and node are proven only in-process.

```mermaid
flowchart LR
    subgraph Mac["Mac dev machine"]
        A["Claude Code and hooks"]
        B["Receipts and transcripts"]
        C["backbone node"]
    end
    subgraph Oracle["Oracle hub"]
        D["backbone serve loopback 8799"]
        E["backbone daemon"]
        F["Hermes adapter UNKNOWN"]
    end
    A --> B
    C -->|"outbound ssh tunnel"| D
    D --> E
    F -.->|"HTTP API, unverified"| D
    G["Telegram"] -.->|"inbound, in-process only"| F
```
