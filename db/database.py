"""SQLite database layer for the Kanban board."""
import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path

HOME = os.path.expanduser("~")
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "kanban.db")


def get_connection() -> sqlite3.Connection:
    """Get a database connection."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cards (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            lane TEXT NOT NULL DEFAULT 'backlog',
            agent TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'triaging',
            project TEXT,
            prompt_sent TEXT,
            output TEXT,
            tokens_spent INTEGER DEFAULT 0,
            project_vision TEXT,
            direct_market TEXT,
            value_exchange TEXT,
            action_chain TEXT,
            next_step TEXT,
            claimed_files TEXT DEFAULT '[]',
            file_verification TEXT DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (card_id) REFERENCES cards(id)
        );

        CREATE TABLE IF NOT EXISTS delegation_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            from_agent TEXT,
            to_agent TEXT,
            action TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (card_id) REFERENCES cards(id)
        );

        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            model TEXT NOT NULL,
            tokens INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (card_id) REFERENCES cards(id)
        );
    """)
    try:
        conn.execute("ALTER TABLE cards ADD COLUMN claimed_files TEXT DEFAULT '[]'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE cards ADD COLUMN file_verification TEXT DEFAULT '{}'")
    except Exception:
        pass
    conn.commit()
    conn.close()


def create_card(card: dict) -> str:
    """Create a new Kanban card and return its ID."""
    import uuid
    card_id = card.get("id", uuid.uuid4().hex[:8])
    conn = get_connection()
    conn.execute("""
        INSERT INTO cards (id, title, lane, agent, model, status, project, prompt_sent, output, tokens_spent)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        card_id,
        card.get("title", "Untitled"),
        card.get("lane", "backlog"),
        card.get("agent", "unknown"),
        card.get("model", "unknown"),
        card.get("status", "triaging"),
        card.get("project"),
        card.get("prompt_sent"),
        card.get("output"),
        card.get("tokens_spent", 0),
    ))
    conn.commit()
    conn.close()
    return card_id


def get_card(card_id: str) -> dict | None:
    """Get a card by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def list_cards(status: str | None = None, lane: str | None = None) -> list[dict]:
    """List cards, optionally filtered by status or lane."""
    conn = get_connection()
    query = "SELECT * FROM cards"
    params = []
    conditions = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if lane:
        conditions.append("lane = ?")
        params.append(lane)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_card(card_id: str, updates: dict) -> bool:
    """Update a card's fields."""
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [card_id]
    conn = get_connection()
    conn.execute(f"UPDATE cards SET {set_clause} WHERE id = ?", values)
    conn.commit()
    changed = conn.total_changes > 0
    conn.close()
    return changed


def add_comment(card_id: str, author: str, body: str) -> int:
    """Add a comment to a card."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO comments (card_id, author, body) VALUES (?, ?, ?)",
        (card_id, author, body),
    )
    conn.commit()
    comment_id = cur.lastrowid
    conn.close()
    return comment_id


def get_comments(card_id: str) -> list[dict]:
    """Get all comments for a card."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM comments WHERE card_id = ? ORDER BY created_at ASC",
        (card_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_delegation_flow(card_id: str, from_agent: str | None, to_agent: str, action: str):
    """Record a delegation flow step."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO delegation_flow (card_id, from_agent, to_agent, action) VALUES (?, ?, ?, ?)",
        (card_id, from_agent, to_agent, action),
    )
    conn.commit()
    conn.close()


def add_token_usage(card_id: str, agent: str, model: str, tokens: int):
    """Record token usage."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO token_usage (card_id, agent, model, tokens) VALUES (?, ?, ?, ?)",
        (card_id, agent, model, tokens),
    )
    conn.commit()
    conn.close()


def get_analytics() -> dict:
    """Get analytics for the dashboard."""
    conn = get_connection()
    total_cards = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    cards_by_status = conn.execute(
        "SELECT status, COUNT(*) FROM cards GROUP BY status"
    ).fetchall()
    cards_by_agent = conn.execute(
        "SELECT agent, COUNT(*) FROM cards GROUP BY agent"
    ).fetchall()
    total_tokens = conn.execute(
        "SELECT SUM(tokens_spent) FROM cards"
    ).fetchone()[0] or 0
    tokens_by_agent = conn.execute(
        "SELECT agent, SUM(tokens_spent) FROM cards GROUP BY agent"
    ).fetchall()
    conn.close()
    return {
        "total_cards": total_cards,
        "cards_by_status": {row[0]: row[1] for row in cards_by_status},
        "cards_by_agent": {row[0]: row[1] for row in cards_by_agent},
        "total_tokens": total_tokens,
        "tokens_by_agent": {row[0]: row[1] for row in tokens_by_agent},
    }
