"""Offline eligibility checks for career work, not a dispatcher or submitter.

All evidence must come from a trusted caller. In particular these checks do not
verify a URL, validate a CV, assess worker independence, or authorize sending.
"""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Evidence:
    scan_succeeded: bool = False
    source_url: str = ''
    live_posting_verified: bool = False
    already_applied: bool = False
    duplicate_state_known: bool = False
    eligibility: str = 'unknown'
    cv_sha256: str = ''
    copy_sha256: str = ''
    copy_gates_passed: bool = False
    reviewer_sha256: str = ''
    review_passed: bool = False


def stage(e: Evidence) -> tuple[str, tuple[str, ...]]:
    """Report the furthest review stage supported by supplied evidence.

    'owner_review' never implies permission to submit. A caller must establish
    reviewer independence and bind a separate approval to the exact artifact.
    """
    if not e.scan_succeeded:
        return 'blocked', ('scan-not-successful',)
    if not re.match(r'^https?://[^/\s]+', e.source_url) or not e.live_posting_verified:
        return 'research', ('live-posting-unverified',)
    if not e.duplicate_state_known:
        return 'qualification', ('application-history-unknown',)
    if e.already_applied:
        return 'hold', ('already-applied',)
    if e.eligibility != 'eligible':
        return 'hold', ('eligibility-' + (e.eligibility if e.eligibility in ('unknown', 'ineligible') else 'unknown'),)
    if not re.fullmatch(r'[0-9a-f]{64}', e.cv_sha256):
        return 'qualification', ('cv-version-unverified',)
    if not re.fullmatch(r'[0-9a-f]{64}', e.copy_sha256) or not e.copy_gates_passed:
        return 'draft', ('copy-or-gates-missing',)
    if not e.review_passed or e.reviewer_sha256 != e.copy_sha256:
        return 'verification', ('exact-copy-review-missing',)
    return 'owner_review', ('submission-not-authorized',)
