# Router invariants

Each is enforced by a test in `tests/test_invariants.py`. Idea (invariants as tests plus a size ratchet) taken from third_party/meta-router; wording is ours.

- **I1** The prompt hooks (`backbone/hook.py`, `scripts/outcome_hook.py`) use no LLM client and no network or process APIs. verify: `test_i1_hooks_llm_and_network_free`
- **I2** The hook fails open: bad input gives empty stdout and exit 0. verify: `test_i2_hook_fails_open`
- **I3** Receipts hold a hash and a length of the prompt, never its text. verify: `test_i3_receipt_has_no_prompt_text`
- **I4** The shadow hook only logs; it prints nothing into the session. verify: `test_i4_shadow_injects_nothing`
- **I5** Nothing in `backbone/`, `eval/`, `scripts/` imports from `third_party/`. verify: `test_i5_third_party_not_imported`
- **I6** The new modules stay under the line budget in `docs/complexity-budget.json`. Raising it is a deliberate edit. verify: `test_i6_size_ratchet`
