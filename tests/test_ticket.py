"""Vault ticket adapter: allowlisted ticket schema, idempotent SQLite submit,
reject malformed/duplicate/unauthorized/over-budget tickets."""
import os
from backbone.ticket import find_tickets, submit_tickets, TicketError
from backbone.ticket import _parse_ticket
from backbone.core import Backbone, load_config

VALID_TICKET = """---
ticket_id: AR-TEST-001
status: ready
execution_authority: preauthorized-internal
data_class: sanitized
goal: run a fake local check
acceptance: exit 0
project: agent-router
allowed_paths: [/tmp]
worker: omp
budget: 60
timeout: 30
gate_name: pytest
side_effects: []
---
body
"""

DUPLICATE_TICKET = VALID_TICKET


def _write_ticket(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_parse_rejects_missing_frontmatter():
    try:
        _parse_ticket("just plain markdown")
        assert False, "should raise TicketError"
    except TicketError:
        pass


def test_parse_rejects_missing_fields():
    try:
        _parse_ticket("---\nticket_id: X\n---\n")
        assert False, "should raise TicketError"
    except TicketError as e:
        assert "missing fields" in str(e)


def test_parse_accepts_both_authority_values():
    for auth in ("preauthorized-internal", "owner-approval-required"):
        t = VALID_TICKET.replace("preauthorized-internal", auth)
        _parse_ticket(t)  # must not raise


def test_parse_rejects_over_budget():
    t = VALID_TICKET.replace("budget: 60", "budget: 99999")
    try:
        _parse_ticket(t)
        assert False, "over-budget ticket should be rejected"
    except TicketError as e:
        assert "budget" in str(e)


def test_parse_rejects_over_timeout():
    t = VALID_TICKET.replace("timeout: 30", "timeout: 99999")
    try:
        _parse_ticket(t)
        assert False, "over-timeout ticket should be rejected"
    except TicketError as e:
        assert "timeout" in str(e)


def test_find_tickets_skips_invalid(tmp_path):
    bad = _write_ticket(tmp_path, "bad.md", "no frontmatter here")
    good = _write_ticket(tmp_path, "good.md", VALID_TICKET)
    found = find_tickets(str(tmp_path))
    skipped = [f for f in found if f.get("_skipped")]
    submitted_ready = [f for f in found if not f.get("_skipped")]
    assert len(skipped) == 1, skipped
    assert len(submitted_ready) == 1, submitted_ready


def test_submit_eligible_ticket_once(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["db"] = str(tmp_path / "backbone.db")
    cfg["gates"] = {"pytest": "python3 -m pytest -q"}
    bb = Backbone(cfg)
    p = _write_ticket(tmp_path, "t.md", VALID_TICKET)
    res = submit_tickets(str(tmp_path), bb)
    submitted = [r for r in res if r.get("submitted")]
    assert len(submitted) == 1, res
    assert submitted[0]["ticket_id"] == "AR-TEST-001"

    # idempotent: second submit finds it already queued
    res2 = submit_tickets(str(tmp_path), bb)
    submitted2 = [r for r in res2 if r.get("submitted")]
    assert submitted2 == [], res2


def test_submit_rejects_duplicate_ticket_id(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["db"] = str(tmp_path / "backbone.db")
    cfg["gates"] = {"pytest": "python3 -m pytest -q"}
    bb = Backbone(cfg)
    p1 = _write_ticket(tmp_path, "a.md", VALID_TICKET)
    p2 = _write_ticket(tmp_path, "b.md", DUPLICATE_TICKET)
    res = submit_tickets(str(tmp_path), bb)
    submitted = [r for r in res if r.get("submitted")]
    rejected = [r for r in res if not r.get("submitted")]
    assert len(submitted) == 1, res
    assert any("duplicate" in (r.get("reason") or "") for r in rejected), rejected


def test_submit_rejects_unauthorized_authority(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["db"] = str(tmp_path / "backbone.db")
    cfg["gates"] = {"pytest": "python3 -m pytest -q"}
    bb = Backbone(cfg)
    t = VALID_TICKET.replace("preauthorized-internal", "owner-approval-required")
    p = _write_ticket(tmp_path, "u.md", t)
    res = submit_tickets(str(tmp_path), bb)
    assert not any(r.get("submitted") for r in res), res
    assert any("owner approval" in (r.get("reason") or "") for r in res), res


def test_submit_rejects_unknown_gate(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["db"] = str(tmp_path / "backbone.db")
    cfg["gates"] = {"pytest": "python3 -m pytest -q"}
    bb = Backbone(cfg)
    t = VALID_TICKET.replace("gate_name: pytest", "gate_name: rm -rf /")
    p = _write_ticket(tmp_path, "g.md", t)
    res = submit_tickets(str(tmp_path), bb)
    assert not any(r.get("submitted") for r in res), res
