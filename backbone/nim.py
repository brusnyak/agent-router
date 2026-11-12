"""Direct NIM chat completion through the key pool (planner, summarizer, classifier calls)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import List, Optional

from .keys import KeyPool, Transient


def chat(pool: KeyPool, messages: List[dict], *, base_url: str, model: str, max_tokens: int = 2048,
         temperature: float = 0.2, prefer: Optional[str] = None, retries: int = 1, backoff_s: float = 3.0,
         timeout: float = 120.0) -> str:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if "nemotron" in model:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    data = json.dumps(body).encode()

    def once(name: str, key: str) -> str:
        req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=data,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code == 429 or e.code >= 500:
                raise Transient(f"http {e.code} on {name}: {detail}")
            raise RuntimeError(f"http {e.code} on {name}: {detail}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            raise Transient(f"{type(e).__name__} on {name}: {e}")
        msg = (payload.get("choices") or [{}])[0].get("message", {})
        text = msg.get("content") or msg.get("reasoning_content") or ""
        if not text.strip():
            raise Transient(f"empty completion on {name}")
        return text

    return pool.call(once, prefer=prefer, retries=retries, backoff_s=backoff_s)
