"""Chat completion against OpenRouter (default model `openrouter/free`, which rotates free models inside one request)."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import List


def _once(messages: List[dict], model: str = "openrouter/free", max_tokens: int = 900, env: dict | None = None,
         timeout: float = 90.0) -> str:
    key = (env or os.environ).get("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode())
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise RuntimeError(f"openrouter: {e}")
    text = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if not text.strip():
        raise RuntimeError("openrouter: empty completion")
    return text


def chat(messages: List[dict], model: str = "openrouter/free", max_tokens: int = 900, env: dict | None = None,
         timeout: float = 90.0, retries: int = 2) -> str:
    """openrouter/free rotates free models per request; an empty or failed one is retried (new request, new model)."""
    last = None
    for _ in range(retries + 1):
        try:
            return _once(messages, model, max_tokens, env, timeout)
        except RuntimeError as e:
            last = e
    raise RuntimeError(str(last))
