# docs: where things are

Read in this order in a fresh session:
1. `VISION.md`: what the router is for and the success test (Soul Knight test). Start here.
2. `../HANDOFF.md`: measured state, what runs, what is open, commands to verify.
3. `AGENT_ROUTER.md`: master spec (topology hub/node, channels, library kinds, pipeline, milestones).
4. `COMPONENTS.md`: what to reuse instead of building (verdicts with licences) and the master build prompt structure.
5. `RESEARCH-AND-REDESIGN.md`: roast + research synthesis, faults found, redesign and build order with gates.
6. `E2E-SCOPE-PLAN.md`, `ADAPTER-RESEARCH.md`: earlier scoping and the Hermes/OpenClaw study.
`archive/` superseded specs (do not follow). `appendix/` old deployment, cross-device and dev-loop notes (still loaded as `loop` rows in the library).

Verify the repo in one line: `python3 -m pytest tests -q` (all green), `python3 eval/check_bundle.py library/bundles` (bundles valid), `python3 -m backbone library counts`.
