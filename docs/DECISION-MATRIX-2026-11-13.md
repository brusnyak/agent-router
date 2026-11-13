# Decision matrix: build, borrow or adopt (2026-11-13)

Status: PROPOSED, not approved. Sources: `research/2026-11-13-{gather,port-plan,landscape-routing-prompts,landscape-curation-evals,teardown,next-steps,label-analysis}.md`.
Labels: proven = checked by the caller this session; reported = worker claim, not re-checked.

## What changed our mind
1. We already own a router: `~/.agent-skills/router/router.py` (427 lines; build, find, hook, guide, check, selftest; local embeddings + TF-IDF; eval harness). Proven: file exists; `settings.json` has 0 references to it; `intake_hook.py:37` is the only caller. We were building a parallel router without measuring this one.
2. Retrieval over the 73-entry catalog is capped: dense top-1 25% / top-3 46% vs 14% guess floor (proven, our scripts). 44 of 73 entries were never invoked in any transcript (proven). Judges split on near-synonyms. Fix the catalog before tuning the retriever.
3. Nothing writes outcome rows, so treat-vs-holdout stays empty unless the hook runs in shadow first (port plan, reported).

## Per part
| Part | Build | Borrow / adopt | Decision |
|---|---|---|---|
| Picker (prompt -> top-3 skills) | thin Python wrapper, stdlib | existing `router.py` (ADAPT, measure first); semantic-router (MIT, 4,034 stars, pushed 2026-11-09, proven) only if router.py fails the gate; bigtool pattern "retrieve then bind" (MIT, 561 stars, proven) | ADAPT router.py; trial semantic-router as drop-in |
| Catalog librarian | scoring script (usage, demand, duplicates, staleness) | cc-skill-usage (MIT, 9 stars, proven; read the code before running), agnix lint (Apache-2.0 per GitHub; worker said MIT), agentskills spec | BUILD small + USE two tools; propose-only, reversible archive, owner approves |
| Upstream-update check | none | only 4 of 73 entries carry an upstream URL; the 5 trees in `~/.agent-skills/vendor/` are the real candidates (reported) | check vendor trees first |
| Prompt compiler (dictation -> 4-field card) | extend `understand.analyze` with `named_things`; add section in `compose.build` (port plan) | one NIM call, fixed JSON schema, entities copied verbatim; GEPA-style tuning later on ~50 labelled dictations (reported) | BUILD in dev mode with owner preview |
| Measurement | JSONL receipt per decision, hash-based 10-20% holdout, sqlite3, two-proportion z-test | promptfoo (MIT, 27,135 stars, proven) for offline replay only | BUILD stdlib; promptfoo optional |
| Context memory (vault/docs) | none yet | existing `vector_memory`; FTS5 first; sqlite-vec only if FTS5 misses; skip mem0, Letta, Graphiti, Langfuse | USE what we own |
| Hook transport | `backbone/hook.py` (does not exist) must be LLM-free and network-free; `rag.py` imports urllib and socket so it cannot sit in it | teardown items 1-8 | BUILD last, shadow first |

## Proposed order (stop at first failed gate)
0. Fix catalog data bug (`scenario-war-room` stored with quotes); generate librarian report v0 from data we already have. No config change.
1. Measure existing `router.py` on the silver set and the short-prompt subset; gate: beats dense baseline top-3 (46% all, 29% lexical short).
2. Owner decision: wire the existing hook path in SHADOW (log only, no injection) to start collecting outcome rows. Needs a `settings.json` edit.
3. Port steps from the port plan: fail-open skeleton, receipts, bypass, eligibility, margin gate, holdout.
4. Compiler dev mode with owner preview; test on the 517 silver prompts (raw vs compiled query).
5. Live hook behind a 20% holdout only if shadow gates pass.

## Needs owner OK (nothing done yet)
- Delete `kind.py` and `tests/test_kind.py` (measured and rejected, 0.31 vs 0.36).
- Edit `~/.claude/settings.json` to register the hook in shadow mode (backup first).
- Run cc-skill-usage read-only on `~/.claude` transcripts after the caller reads its code.

## Known weaknesses
- Silver labels are LLM-made and unverified by a human; the compiler test is partly circular.
- Several landscape stars and dates are worker-reported; three spot-checked here, one error found (agnix license).
- `router.py` quality is unmeasured. Its sibling `route_dryrun.py` failed a 6-of-10 kill test (gather report).
