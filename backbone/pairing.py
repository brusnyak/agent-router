"""Telegram pairing: the user sends /start to the bot, we capture THEIR chat id from getUpdates (not a bot id), verify with a
test message, and store both values in a 600-mode local secrets file. Token comes from the environment and is never printed."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


def _api(tok: str, method: str, payload: dict, timeout: int = 35) -> dict:
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "description": e.read().decode(errors="replace")[:200]}


def pair(tok: str, store_path: str, wait_s: int = 120, api: Optional[Callable] = None) -> dict:
    """Wait up to wait_s for a human /start; returns {ok, chat_id, username, reason}. Writes store_path only on success."""
    api = api or (lambda m, p, t=35: _api(tok, m, p, t))
    me = api("getMe", {})
    if not me.get("ok"):
        return {"ok": False, "reason": f"token rejected: {me.get('description') or me.get('http')}"}
    if api("getWebhookInfo", {}).get("result", {}).get("url"):
        return {"ok": False, "reason": "a webhook is set on this bot; another service owns it. Use a dedicated bot for the router."}
    deadline, offset = time.time() + wait_s, 0
    while time.time() < deadline:
        r = api("getUpdates", {"offset": offset, "timeout": 20}, 30)
        if not r.get("ok"):
            return {"ok": False, "reason": f"getUpdates failed ({r.get('http')}): {r.get('description')}; another process may be polling this bot"}
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            frm, chat = m.get("from", {}), m.get("chat", {})
            if frm.get("is_bot") or chat.get("type") != "private" or not str(m.get("text", "")).startswith("/start"):
                continue
            sent = api("sendMessage", {"chat_id": chat["id"], "text": "Agent Router paired. This chat receives job reports and can send /run, /status, /nodes."})
            if not sent.get("ok"):
                return {"ok": False, "reason": f"paired chat but test send failed: {sent.get('description')}"}
            p = Path(store_path)
            keep = [ln for ln in (p.read_text().splitlines() if p.exists() else []) if ln.split("=", 1)[0] not in KEYS]
            p.write_text("\n".join(keep + [f"TELEGRAM_BOT_TOKEN={tok}", f"TELEGRAM_CHAT_ID={chat['id']}"]) + "\n")
            os.chmod(p, 0o600)
            return {"ok": True, "chat_id": chat["id"], "username": me["result"].get("username"), "reason": ""}
    return {"ok": False, "reason": f"no /start received within {wait_s}s: open the bot in Telegram and press Start"}
