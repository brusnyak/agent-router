import sqlite3
from backbone.watch import latest_sha, changed


def fake_run(sha):
    return lambda args: sha


def test_latest_sha_uses_gh_api_and_strips():
    seen = {}

    def run(args):
        seen["args"] = args
        return "abc123\n"

    assert latest_sha("owner/repo", run=run) == "abc123"
    assert seen["args"][:2] == ["api", "repos/owner/repo/commits/HEAD"]


def test_changed_first_seen_then_same_then_new():
    con = sqlite3.connect(":memory:")
    assert changed(con, "o/r", run=fake_run("a1")) is True
    assert changed(con, "o/r", run=fake_run("a1")) is False
    assert changed(con, "o/r", run=fake_run("b2")) is True
    assert changed(con, "o/r", run=fake_run("b2")) is False
    assert changed(con, "o/other", run=fake_run("b2")) is True


def test_gh_failure_means_no_change_not_crash():
    con = sqlite3.connect(":memory:")

    def boom(args):
        raise RuntimeError("gh failed")

    assert changed(con, "o/r", run=boom) is False
