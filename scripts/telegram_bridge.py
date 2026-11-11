#!/usr/bin/env python3
"""Telegram bridge for agent-router.

Connects the Mac agent-router to Telegram for cross-device monitoring and
dispatch. Sends card summaries, PEEM scores, drift proposals, and proactive
loop reports to Telegram. Receives commands from Telegram to dispatch tasks.

Never installs anything — uses python-telegram-bot if available, otherwise
falls back to raw Bot API HTTP requests via urllib (stdlib only).

Configuration:
  TELEGRAM_BOT_TOKEN — bot token from @BotFather
  TELEGRAM_CHAT_ID   — target chat ID for messages
  AGENT_ROUTER_URL   — FastAPI backend URL (default http://127.0.0.1:8080)
  POLL_INTERVAL      — seconds between Telegram getUpdates polls (default 5)

Usage:
  python scripts/telegram_bridge.py          # run bridge (send + receive)
  python scripts/telegram_bridge.py --send-only  # only send, don't poll
  python scripts/telegram_bridge.py --test     # send a test message
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
CONFIG_DIR = os.path.join(PROJECT_ROOT, "config")
DB_PATH = os.path.join(PROJECT_ROOT, "kanban.db")

# ── Configuration ──────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AGENT_ROUTER_URL = os.environ.get("AGENT_ROUTER_URL", "http://127.0.0.1:8080")
POLL_INTERVAL = int(os.environ.get("TELEGRAM_POLL_INTERVAL", "5"))

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# ── Helpers ────────────────────────────────────────────────────────────────

def tg_send_message(text: str, parse_mode: str = "Markdown", reply_markup: Optional[dict] = None) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — skipping send.", file=sys.stderr)
        return False
    payload: Dict[str, Any] = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{TELEGRAM_API}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.URLError as e:
        print(f"Telegram send failed: {e}", file=sys.stderr)
        return False


def tg_get_updates(offset: int) -> List[dict]:
    """Poll Telegram for new updates. Returns list of update dicts."""
    if not BOT_TOKEN:
        return []
    url = f"{TELEGRAM_API}/getUpdates?offset={offset}&timeout={POLL_INTERVAL}&limit=10"
    try:
        with urllib.request.urlopen(url, timeout=POLL_INTERVAL + 5) as resp:
            body = json.loads(resp.read().decode())
            return body.get("result", [])
    except Exception:
        return []


# ── Agent-router API ──────────────────────────────────────────────────────

def ar_chat(message: str, project: Optional[str] = None) -> dict:
    """Send a chat message to agent-router and return the result."""
    payload: Dict[str, Any] = {"message": message}
    if project:
        payload["project"] = project
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{AGENT_ROUTER_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def ar_list_cards(status: Optional[str] = None, lane: Optional[str] = None) -> List[dict]:
    """List kanban cards from agent-router."""
    url = f"{AGENT_ROUTER_URL}/api/cards"
    params = []
    if status:
        params.append(f"status={status}")
    if lane:
        params.append(f"lane={lane}")
    if params:
        url += "?" + "&".join(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            return body.get("cards", [])
    except Exception:
        return []


def ar_analytics() -> dict:
    """Get agent-router analytics."""
    try:
        with urllib.request.urlopen(f"{AGENT_ROUTER_URL}/api/analytics", timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return {}


# ── Message formatters ────────────────────────────────────────────────────

def format_card(card: dict) -> str:
    """Format a single card for Telegram."""
    return (
        f"*Card #{card.get('id', '?')}*\n"
        f"Lane: {card.get('lane', '?')} | Agent: {card.get('agent', '?')}\n"
        f"Model: {card.get('model', '?')}\n"
        f"Status: {card.get('status', '?')}\n"
        f"Tokens: {card.get('tokens_spent', 0)}\n"
        f"Project: {card.get('project', '—')}\n"
        f"Output: {(card.get('output') or '')[:200]}…\n"
    )


def format_drift(drift: dict) -> str:
    """Format config drift proposals for Telegram."""
    lines = ["*Config Drift Proposals* (suggest + gate — not auto-applied)"]
    for c in drift.get("routing_constraints", []):
        lines.append(f"🚫 {c}")
    for p in drift.get("proposals", []):
        lines.append(f"📝 {p.get('target', '?')}: {p.get('issue', '?')}")
    return "\n".join(lines) if len(lines) > 1 else "No drift proposals."


# ── Commands ──────────────────────────────────────────────────────────────

CMD_HELP = """*Agent Router — Telegram Commands*

/status — router health + agents + models
/cards — recent open kanban cards
/drift — config drift proposals (PEEM feedback)
/dispatch <task> — dispatch a task to the router
/analytics — token usage analytics
/help — this message
"""

def cmd_help() -> str:
    return CMD_HELP

def cmd_status() -> str:
    agents = []
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from graph.supervisor import RouterSupervisor
        s = RouterSupervisor()
        agents = s.get_agents()
        models = s.get_available_models()
    except Exception:
        pass
    lines = ["*Agent Router Status*"]
    for a in agents:
        mark = "✅" if a.get("available") else "❌"
        lines.append(f"{mark} {a['id']} ({a.get('provider', '?')}) — {a.get('route_reasons', [])}")
    lines.append("")
    lines.append("*Models:*")
    for m in models:
        mark = "✅" if m.get("available") else "❌"
        lines.append(f"{mark} {m['id']} — {m.get('name', '?')} ({m.get('role', '?')})")
    return "\n".join(lines)

def cmd_cards() -> str:
    cards = ar_list_cards(status="running")
    if not cards:
        cards = ar_list_cards(status="triaging")
    if not cards:
        return "No open cards."
    lines = ["*Recent Open Cards:*"]
    for c in cards[:5]:
        lines.append(f"#{c.get('id')} [{c.get('lane')}] {c.get('agent')} — {(c.get('title') or '')[:60]}")
    return "\n".join(lines)

def cmd_dispatch(text: str) -> str:
    result = ar_chat(text)
    status = result.get("status", "?")
    lane = result.get("lane", "?")
    agent = result.get("agent", "?")
    card_id = (result.get("card") or {}).get("id", "?")
    result_text = (result.get("result") or "")[:200]
    interrupt = result.get("interrupt_reason")
    lines = [
        f"*Dispatch Result*",
        f"Status: {status}",
        f"Lane: {lane} | Agent: {agent}",
        f"Card: #{card_id}",
    ]
    if interrupt:
        lines.append(f"⚠️ Interrupted: {interrupt}")
    if result_text:
        lines.append(f"Output: {result_text}…")
    return "\n".join(lines)

def cmd_analytics() -> str:
    a = ar_analytics()
    if not a:
        return "Analytics unavailable."
    lines = ["*Token Analytics*"]
    lines.append(f"Total cards: {a.get('total_cards', 0)}")
    lines.append(f"Total tokens: {a.get('total_tokens', 0)}")
    lines.append("")
    lines.append("*By agent:*")
    for agent, count in a.get("cards_by_agent", {}).items():
        lines.append(f"  {agent}: {count} cards")
    return "\n".join(lines)


# ── Main loop ─────────────────────────────────────────────────────────────

def handle_command(text: str) -> str:
    """Parse a Telegram command and return the response text."""
    text = text.strip()
    if text == "/start" or text == "/help":
        return cmd_help()
    if text == "/status":
        return cmd_status()
    if text == "/cards":
        return cmd_cards()
    if text == "/drift":
        import json as _json
        drift_path = os.path.join(CONFIG_DIR, "drift", "config-drift.yaml")
        if os.path.exists(drift_path):
            # Minimal YAML parse without pyyaml
            lines = []
            in_constraints = False
            in_proposals = False
            for line in open(drift_path):
                line = line.rstrip()
                if line.startswith("routing_constraints:"):
                    in_constraints = True
                    in_proposals = False
                    continue
                if line.startswith("proposals:"):
                    in_proposals = True
                    in_constraints = False
                    continue
                if line.startswith("#") or not line.strip():
                    continue
                if in_constraints and line.startswith("  - "):
                    lines.append(f"🚫 {line[4:]}")
                    in_proposals = False
                elif in_proposals and line.startswith("  - target:"):
                    target = line.split("target:", 1)[1].strip()
                    lines.append(f"📝 {target}")
                    in_constraints = False
            return "\n".join(lines) if lines else "No drift proposals."
        return "No drift file found."
    if text.startswith("/dispatch "):
        task = text[len("/dispatch "):].strip()
        if not task:
            return "Usage: /dispatch <task description>"
        return cmd_dispatch(task)
    if text == "/analytics":
        return cmd_analytics()
    return f"Unknown command: {text}\n\n{CMD_HELP}"


def run_send_only() -> int:
    """Send a test message and exit."""
    ok = tg_send_message("🤖 Agent Router bridge online.\nUse /help for commands.")
    return 0 if ok else 1


def run_poll() -> int:
    """Poll Telegram for commands and dispatch to agent-router."""
    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required for poll mode.", file=sys.stderr)
        return 1
    offset = 0
    print(f"Telegram bridge polling (chat {CHAT_ID})...")
    while True:
        updates = tg_get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            text = msg.get("text", "")
            if not text:
                continue
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if chat_id != CHAT_ID:
                continue  # ignore messages from other chats
            response = handle_command(text)
            tg_send_message(response)
        time.sleep(1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Telegram bridge for agent-router")
    ap.add_argument("--send-only", action="store_true", help="Send test message and exit")
    ap.add_argument("--test", action="store_true", help="Alias for --send-only")
    args = ap.parse_args()
    if args.send_only or args.test:
        return run_send_only()
    return run_poll()


if __name__ == "__main__":
    sys.exit(main())
