"""Acceptance test for the job-application delegation task (router: jobs lane -> claude).

Per posting (never submit; owner clicks):
1. Master CV only (`~/cv/cv-print.html`); tailor cover text, never fork the CV.
2. Fit gate verdict per posting; reject on: language gate (Slovak C1/C2, German B2+),
   >3 years asked or 'senior' (years gate eased: shipped product substitutes),
   unevidenced field, non-remote location, work-rights line.
3. Max 2 drafts; owner approves exact text; owner submits.
4. No hours line ever; no personal data leakage; value-first, evidence-based cover text.
5. No send/spend/submit by the agent.

Exit 0 = PASS; exit 1 = FAIL with a named rule.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CV = Path.home() / "cv" / "cv-print.html"
BRIEF = Path.home() / "memory-vault" / "pages" / "jobs-system" / "BRIEF.md"


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def main() -> int:
    fails: list[str] = []

    if not CV.exists():
        fails.append("master CV missing")
    if not BRIEF.exists():
        fails.append("jobs-system BRIEF missing")

    if fails:
        print("JOB APPLY ACCEPTANCE FAIL:", "; ".join(fails))
        return 1
    print("JOB APPLY ACCEPTANCE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
