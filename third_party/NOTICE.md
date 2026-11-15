# Third-party reference code (read-only study copies)
Files here are unmodified copies kept so our Python ports can cite exact lines. They are NOT built or run. Both projects are Apache-2.0; each folder keeps its own LICENSE/NOTICE.
- meta-router: https://github.com/dmmdea/meta-router @ ad18c1a (copied 2026-11-13)
- agent-router: https://github.com/FlorianBruniaux/agent-router @ e1343ff (copied 2026-11-13)
Our ports (Python, stdlib) credit the source file:line in a comment and are written independently from the described behavior.
- litellm-adaptive: https://github.com/BerriAI/litellm @ 91fc6c20 (MIT, copied 2026-11-15; litellm/router_strategy only, not enterprise/). Thompson-sampling bandit per (request type, model), tier priors, stall detector, latency picker. Our port: backbone/bandit.py, reward = hard gate result instead of regex signals.
- portkey-conditional: https://github.com/Portkey-AI/gateway @ 669825c (MIT, copied 2026-11-15). conditionalRouter.ts: $eq/$in/$regex/$and/$or query operators resolving to targets with fallbacks. Our port: backbone/plan.py rules from config/routes.yaml.
- jcode-notes: https://github.com/1jehuang/jcode @ 13c724f (MIT). Only the headless-memory bench script is kept; jcode is used as a worker (`jcode run -p nvidia-nim --json`), not copied. Speed claims are self-reported; we measure.
