"""Tests for the indexer script."""
import json
import os
import sys
from pathlib import Path

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)

from scripts.index_vault import discover_corpus, build_index, search, INDEX_DB, tokenize


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
    """build_index() creates index.db and returns info dict."""
    docs = discover_corpus()
    info = build_index(docs)
    assert "indexed_docs" in info
    assert "index_path" in info
    assert info["indexed_docs"] > 0
    assert os.path.exists(info["index_path"])


def test_index_db_has_tables():
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


def test_search_known_document():
    """search() can find the agent-router README."""
    docs = discover_corpus()
    build_index(docs)
    results = search("LangGraph multi-agent router Kanban", top_k=10)
    # Should find the agent-router README
    readme_found = any("agent-router" in r.get("id", "") and "README.md" in r.get("id", "") and "node_modules" not in r.get("id", "") for r in results)
    assert readme_found, f"agent-router README not found in top 10: {[r['id'] for r in results]}"


if __name__ == "__main__":
    test_tokenize()
    test_discover_corpus_returns_docs()
    test_build_index_creates_db()
    test_index_db_has_tables()
    test_search_returns_results()
    test_search_empty_query()
    test_search_known_document()
    print("All indexer tests passed.")
