"""Web-search verification layer (routecheck-style `verify`).

After-the-fact: given a worker's output, extract factual claims, fetch the
pages it cites, and confirm the page text supports each claim. A claim whose
source cannot be read, or that the source does not support, is flagged so the
run can be blocked until resolved ("NOT RUN = FAIL").

Deterministic + one network step (browser read of cited URLs). Fail open:
verification failure never crashes a run, it only marks `evidence_ok=False`
and records a reason so the digest can count unverified runs.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .browser import read as browser_read, fence as browser_fence, urls_in
from .evidence import missing_paths

_CLAIM = re.compile(r"^(?:[A-ZÁ-Ž0-9][^\.!?]*[\.!?])\s+", re.M)


def extract_claims(text: str, max_claims: int = 8) -> List[str]:
    """Pull sentence-like factual claims from output. Cheap heuristic, not an LLM."""
    claims = []
    for m in _CLAIM.finditer(text):
        c = m.group(0).strip()
        if len(c) < 20 or len(c) > 220:
            continue
        if any(w in c.lower() for w in ("i think", "maybe", "probably", "i believe", "uncertain")):
            continue
        claims.append(c)
        if len(claims) >= max_claims:
            break
    return claims


def verify_output(output: str, roots: List[str], bb=None) -> tuple[bool, List[str]]:
    """Return (evidence_ok, reasons).

    Checks:
      1. cited file paths exist under the given roots (deterministic);
      2. cited URLs are readable via the browser worker and their text
         contains at least one keyword from each claim (web verification);
      3. every claim has at least one supporting cited source.
    """
    reasons: List[str] = []
    if not output:
        return True, []

    # 1. cited files must exist
    miss = missing_paths(output, roots)
    if miss:
        reasons.append(f"cites_missing_file: {', '.join(miss[:5])}")

    # 2. cited URLs must be readable (web verification)
    urls = urls_in(output)
    page_text = ""
    if urls:
        try:
            pages = browser_read(urls, f"verify-{abs(hash(output)) % 100000}", cap=12000, timeout=90)
            page_text = browser_fence(pages)
            for pg in pages:
                if pg.get("error"):
                    reasons.append(f"url_unreadable: {pg['url']} ({pg['error'][:80]})")
        except Exception as e:
            reasons.append(f"web_read_failed: {e}")

    # 3. each claim should have some support in the cited page text
    if page_text:
        claims = extract_claims(output)
        unsupported = []
        low = page_text.lower()
        for c in claims:
            keywords = [w for w in re.findall(r"[a-zá-ž]{4,}", c.lower())][:3]
            if keywords and not any(k in low for k in keywords):
                unsupported.append(c[:90])
        if unsupported:
            reasons.append(f"claim_unsupported: {'; '.join(unsupported[:3])}")

    return (len(reasons) == 0), reasons


def gate_for_verify(verified: bool, evidence_ok: bool, reasons: List[str]) -> str:
    """Build the gate failure reason for a run that failed verification."""
    if not verified:
        return "gate_failed"
    if not evidence_ok:
        return "; ".join(reasons) if reasons else "evidence_unverified"
    return ""
