"""Best-effort Telegram notify. stdlib only; never raises. Creds: env TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID,
else a local .env next to the repo (VM: chmod 600). Silent no-op when unset."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


ALIASES = {"TELEGRAM_BOT_TOKEN": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"), "TELEGRAM_CHAT_ID": ("TELEGRAM_CHAT_ID", "TELEGRAM_ID")}


def _cred(name: str) -> str:
    names = ALIASES.get(name, (name,))
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    root = Path(__file__).resolve().parent.parent
    for fn in (".env.local", ".env"):  # the router's own bot first
        f = root / fn
        if f.exists():
            for line in f.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() in names and v.strip():
                    return v.strip().strip("'\"")
    return ""


def notify(text: str) -> bool:
    tok, chat = _cred("TELEGRAM_BOT_TOKEN"), _cred("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                     json.dumps({"chat_id": chat, "text": text[:3500]}).encode(),
                                     {"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=10).status == 200
    except Exception:
        return False
