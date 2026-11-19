PiWorker now checks combined stdout/stderr for response truncation and context/output token-limit markers before empty-output and transient retry handling.
Detected truncation returns terminal Result with failure_kind=truncated, retryable=false, actual pi:NIM_x worker and key_slot, and a bounded 300-character diagnostic.
Regression drives nonzero exit + empty stdout + token-limit stderr through Backbone.run; confirms one process invocation, blocked terminal receipt, and selected key slot.
`python3` AST parse of workers.py and test_worker_key_routing.py -> PASS.
`.venv/bin/python -m pytest -q tests/test_worker_key_routing.py tests/test_backbone.py::test_pi_timeout_is_not_retried_on_other_keys` -> 22 passed in 0.44s.
`git diff --check -- backbone/workers.py tests/test_worker_key_routing.py` -> PASS.
No credentials, env files, network, model calls, or delegation used.
preflight: reused PiWorker and code rules from lessons-never-repeat.md.
suggest: add further truncation phrases only when backed by captured provider diagnostics.
