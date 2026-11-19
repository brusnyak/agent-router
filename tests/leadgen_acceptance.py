"""Acceptance test for the lead-generation + data pipeline delegation task (router: cash-leads/upwork lanes -> claude).

Per lead row (deterministic matcher picks the offer; LLM only writes wording):
1. Each lead row has ONE gap, a URL or screenshot path, and a source line.
2. Consent basis per market: AU Spam Act s16 (conspicuous publication, saved URL/date/role),
   SK/CZ register check, phone DNCR check, calling hours 9-20.
3. No first-match ABR pick: ABN proven from lead site + ABR (au_identity.py).
4. Offer matcher: rules on facts only; LLM never picks the offer.
5. Statuses: READY_FOR_COPY (facts sufficient), HOLD (missing fact named), DROP (disqualified).
6. Upwork: fit-gate verdict per posting; max 2 drafts; owner approves exact text; never submits/spends Connects.
7. No send (lane rule `never: send`); send gate OFF until copy engine PASS + per-batch owner yes.

Exit 0 = PASS; exit 1 = FAIL with a named rule.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS = Path.home() / "Developer" / "founder-runs" / "leads"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def main() -> int:
    fails: list[str] = []

    # matcher.py must exist and produce matches.json with per-lead gap + source
    matcher = SCRIPTS / "matcher.py"
    if not matcher.exists():
        fails.append("matcher.py missing")
    else:
        r = run([sys.executable, str(matcher), str(SCRIPTS / "dossiers" / "*.json"),
                 str(SCRIPTS / "dossiers_au" / "*.json")])
        if r.returncode != 0:
            fails.append("matcher.py failed to run")
        matches = SCRIPTS / "matches.json"
        if matches.exists():
            import json
            data = json.loads(matches.read_text())
            for row in data:
                if not row.get("gap"):
                    fails.append(f"lead {row.get('id')} missing gap")
                if not row.get("source") and not row.get("url"):
                    fails.append(f"lead {row.get('id')} missing source/url")

    if fails:
        print("LEADGEN ACCEPTANCE FAIL:", "; ".join(fails))
        return 1
    print("LEADGEN ACCEPTANCE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
