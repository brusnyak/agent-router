"""Tests for the indexer script."""
import json
import os
import sys
from pathlib import Path

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.index_vault import discover_corpus, build_index, search, INDEX_DB, tokenize

import pytest


def _need_corpus():
    if not discover_corpus():
        pytest.skip("machine-local corpus absent (vault, skills, refs)")


def test_tokenize():
    """tokenize() splits text into lowercase tokens of 3+ chars."""
    toks = tokenize("Hello World! Agent-router test.")
    assert "hello" in toks
    assert "world" in toks
    assert "agent-router" in toks
    assert "test" in toks
    # Short tokens should be filtered
    assert "a" not in toks
    assert "is" not in toks


def test_discover_corpus_returns_docs():
    _need_corpus()
    """discover_corpus() returns a list of doc dicts."""
    docs = discover_corpus()
    assert isinstance(docs, list)
    assert len(docs) > 0
    for d in docs:
        assert "id" in d
        assert "path" in d
        assert "kind" in d
        assert "text" in d


def test_build_index_creates_db():
    _need_corpus()
    """build_index() creates index.db and returns info dict."""
    docs = discover_corpus()
    info = build_index(docs)
    assert "indexed_docs" in info
    assert "index_path" in info
    assert info["indexed_docs"] > 0
    assert os.path.exists(info["index_path"])


def test_index_db_has_tables():
    _need_corpus()
    """index.db contains fts, tfidf_meta, and idf tables."""
    import sqlite3
    docs = discover_corpus()
    build_index(docs)
    conn = sqlite3.connect(INDEX_DB)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    conn.close()
    assert "fts" in tables
    assert "tfidf_meta" in tables
    assert "idf" in tables


def test_search_returns_results():
    _need_corpus()
    """search() returns ranked results."""
    docs = discover_corpus()
    build_index(docs)
    results = search("agent router dispatch kanban", top_k=5)
    assert isinstance(results, list)
    assert len(results) > 0
    for r in results:
        assert "id" in r
        assert "path" in r
        assert "kind" in r
        assert "score" in r


def test_search_empty_query():
    """search() with empty query returns empty list."""
    results = search("")
    assert results == []


def test_search_known_document(tmp_path, monkeypatch):
    """search() ranks the agent-router README for its own topic. Hermetic: tiny fixed corpus and a temp index, not the live vault."""
    from scripts import index_vault
    monkeypatch.setattr(index_vault, "INDEX_DB", str(tmp_path / "index.db"))
    mk = lambda i, t: {"id": i, "path": i, "kind": "doc", "text": t}
    docs = [mk("doc:/p/agent-router/README.md", "agent-router: LangGraph multi-agent router with a Kanban board and worker gates"),
            mk("doc:/p/notes/cooking.md", "pasta recipe with tomatoes and basil"),
            mk("doc:/p/notes/trading.md", "futures risk sizing and stop losses"),
            mk("doc:/p/notes/design.md", "color palette contrast and typography scale")]
    index_vault.build_index(docs)
    results = index_vault.search("LangGraph multi-agent router Kanban", top_k=3)
    assert results and results[0]["id"] == "doc:/p/agent-router/README.md", [r["id"] for r in results]


if __name__ == "__main__":
    test_tokenize()
    test_discover_corpus_returns_docs()
    test_build_index_creates_db()
    test_index_db_has_tables()
    test_search_returns_results()
    test_search_empty_query()
    test_search_known_document()
    print("All indexer tests passed.")
