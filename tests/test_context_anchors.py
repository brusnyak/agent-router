"""Offline project-anchor integration with temporary config and a fake provider."""
import socket
from unittest.mock import Mock

import pytest

from backbone.context import Sessions, est_tokens
from backbone.db import connect


HEADER = "## PROJECT ANCHORS + RECALL (sources shown; vault wins on conflict)\n"


@pytest.fixture
def context(tmp_path, monkeypatch):
    from backbone import retrieval

    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    anchor = tmp_path / "master-plan.md"
    anchor.write_text("MASTER PLAN: ship project anchors\n", encoding="utf-8")
    projects = tmp_path / "projects.yaml"
    projects.write_text(
        "projects:\n"
        "  - id: anchored\n"
        f"    path: {tmp_path}\n"
        "    anchors:\n"
        "      - master-plan.md\n"
        "  - id: plain\n"
        f"    path: {tmp_path}\n",
        encoding="utf-8",
    )
    provider = Mock(name="fake_provider")
    provider.search.return_value = [retrieval.Hit("fake", "Fake recall", "PROVIDER TEXT", 1, "fake.md")]
    registry = retrieval.Registry(providers=[provider], projects_path=projects)
    factory = Mock(return_value=registry)
    monkeypatch.setattr(retrieval, "Registry", factory)
    con = connect(str(tmp_path / "context.db"))
    sessions = Sessions(con, {"budget_tokens": 4000})
    monkeypatch.setattr(sessions, "recall", Mock(return_value=["SESSION RECALL"]))
    monkeypatch.setattr(sessions, "vault", Mock(return_value=["LEGACY VAULT"]))
    sid = sessions.open(project="anchored")
    return sessions, sid, registry, factory, provider


def test_anchors_precede_other_context_without_duplicate_vault(context):
    sessions, sid, registry, factory, provider = context
    packed = sessions.pack(sid, "ship anchors", pinned="PINNED", library_notes="LIBRARY", project="anchored")
    assert packed.startswith(HEADER)
    assert packed.index("MASTER PLAN") < packed.index("PROVIDER TEXT") < packed.index("PINNED")
    assert packed.index("MASTER PLAN") < packed.index("SESSION RECALL")
    assert "source:" in packed and "master-plan.md" in packed
    assert "LEGACY VAULT" not in packed
    sessions.vault.assert_not_called()
    provider.search.assert_called_once_with("ship anchors", 5)


def test_run_project_is_available_from_session(context):
    sessions, sid, *_ = context
    assert "MASTER PLAN" in sessions.pack(sid, "ship anchors")


def test_retrieval_failure_falls_back_without_stdout(context, monkeypatch, capsys):
    sessions, sid, registry, *_ = context
    monkeypatch.setattr(registry, "context_pack", Mock(side_effect=RuntimeError("unavailable")))
    packed = sessions.pack(sid, "ship anchors", project="anchored")
    assert "LEGACY VAULT" in packed and HEADER not in packed
    assert capsys.readouterr().out == ""


def test_empty_pack_falls_back(context, monkeypatch):
    sessions, sid, registry, *_ = context
    monkeypatch.setattr(registry, "context_pack", Mock(return_value=""))
    assert "LEGACY VAULT" in sessions.pack(sid, "ship anchors", project="anchored")


def test_no_vault_skips_registry_and_vault(context):
    sessions, sid, registry, factory, provider = context
    packed = sessions.pack(sid, "ship anchors", project="anchored", use_vault=False)
    factory.assert_not_called()
    provider.search.assert_not_called()
    sessions.vault.assert_not_called()
    assert HEADER not in packed and "SESSION RECALL" in packed


@pytest.mark.parametrize("project", ["plain", "unknown", ""])
def test_project_without_anchors_is_unchanged(context, project):
    sessions, sid, registry, factory, provider = context
    expected = "## Pinned\nPINNED\n\n## Retrieved\nSESSION RECALL\nLEGACY VAULT\n\n## Task\nship anchors"
    assert sessions.pack(sid, "ship anchors", pinned="PINNED", project=project) == expected
    provider.search.assert_not_called()


def test_anchor_cap_and_total_budget(context, monkeypatch):
    sessions, sid, registry, *_ = context
    monkeypatch.setattr(registry, "context_pack", Mock(return_value="A" * 7000))
    packed = sessions.pack(sid, "ship anchors", project="anchored")
    block = packed.split(HEADER, 1)[1].split("\n\n", 1)[0]
    assert block == "A" * 6000
    sessions.budget = 100
    assert est_tokens(sessions.pack(sid, "ship anchors", project="anchored")) <= 100
