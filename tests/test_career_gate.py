from dataclasses import replace

import pytest

from backbone.career_gate import Evidence, stage


SHA = 'a' * 64
READY = Evidence(scan_succeeded=True, source_url='https://example.invalid/job/123',
                 live_posting_verified=True, duplicate_state_known=True,
                 eligibility='eligible', cv_sha256=SHA, copy_sha256=SHA,
                 copy_gates_passed=True, reviewer_sha256=SHA, review_passed=True)


@pytest.mark.parametrize('changes, expected', [
    ({'scan_succeeded': False}, 'blocked'),
    ({'live_posting_verified': False}, 'research'),
    ({'source_url': 'file:///tmp/posting'}, 'research'),
    ({'duplicate_state_known': False}, 'qualification'),
    ({'already_applied': True}, 'hold'),
    ({'eligibility': 'unknown'}, 'hold'),
    ({'eligibility': 'ineligible'}, 'hold'),
    ({'cv_sha256': ''}, 'qualification'),
    ({'copy_gates_passed': False}, 'draft'),
    ({'reviewer_sha256': 'b' * 64}, 'verification'),
    ({'review_passed': False}, 'verification'),
])
def test_missing_or_negative_evidence_cannot_reach_owner_review(changes, expected):
    assert stage(replace(READY, **changes))[0] == expected


def test_review_never_authorizes_submission():
    assert stage(READY) == ('owner_review', ('submission-not-authorized',))
