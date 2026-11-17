# Router oversight implementation plan

Goal: understandable OMP status, active task details, explicit unknown/stale states.
Approved design: inline summary plus on-demand /router panel, no permanent corner overlay.
Reuse: backbone/status.py, existing runs/jobs/steps tables, current OMP extension.

- [x] Router NIM worker updates collector and stages extension (run f1ee36c9).
- [x] Coordinator review, syntax and live read-only status; 16 offline fixture tests pass after corrections.
- [x] Extension installed with backup ~/.omp/agent/extensions/router-status.ts.20261117T162055.bak.
- [x] Installed OMP 18.22.0 smoke: width 40/80/120, polling, details and shutdown PASS; existing sessions need restart for command registration.
- [x] Chat free-worker partial patch (14620c69) reviewed and completed locally; original palette/type preserved per owner's clarification.
- [x] Chat static gate 191 PASS; JS/build checks; 8 browser regression checks PASS; Nina 1280/390 light/dark inspected; Mimoza desktop identity smoke.
- [x] Deployable artifact/report prepared. Production deployment and git push remain unperformed pending authorization.

Constraints: free configured NIM workers; no paid escalation; one worker at a time; preserve unrelated dirty files; no installs; no fabricated delegation relationships; existing stack and palette.
