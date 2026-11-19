"""Direct NIM chat completion through the key pool (planner, summarizer, classifier calls)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Iterator, List, Optional

from . import otel
from .keys import KeyPool, Transient


def _nim_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _nim_body(model: str, messages: List[dict], max_tokens: int, temperature: float, stream: bool) -> dict:
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "stream": stream}
    if "nemotron" in model:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    return body


def chat(pool: KeyPool, messages: List[dict], *, base_url: str, model: str, max_tokens: int = 2048,
         temperature: float = 0.2, prefer: Optional[str] = None, retries: int = 1, backoff_s: float = 3.0,
         timeout: float = 120.0, on_key=None) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(_nim_body(model, messages, max_tokens, temperature, False)).encode()

    def once(name: str, key: str) -> str:
        if on_key:
            on_key(name)
        req = urllib.request.Request(url, data=data, headers=_nim_headers(key))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code == 429 or e.code >= 500:
                t = Transient(f"http {e.code} on {name}: {detail}")
                ra = e.headers.get("Retry-After") if e.code == 429 and e.headers else None
                t.retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                raise t
            if e.code in (401, 403):   # revoked/expired key: park it for an hour and fail over to the next key
                t = Transient(f"http {e.code} on {name}: key rejected")
                t.retry_after = 3600.0
                raise t
            raise RuntimeError(f"http {e.code} on {name}: {detail}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            raise Transient(f"{type(e).__name__} on {name}: {e}")
        msg = (payload.get("choices") or [{}])[0].get("message", {})
        choice = (payload.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("NIM completion truncated: finish_reason=length")
        text = msg.get("content") or msg.get("reasoning_content") or ""
        if not text.strip():
            raise Transient(f"empty completion on {name}")
        return text

    with otel.span(
        "router.llm.chat",
        {"llm.model": model, "llm.base_url": base_url, "llm.stream": False},
    ):
        return pool.call(once, prefer=prefer, retries=retries, backoff_s=backoff_s)


def chat_stream(pool: KeyPool, messages: List[dict], *, base_url: str, model: str, max_tokens: int = 2048,
                temperature: float = 0.2, prefer: Optional[str] = None, timeout: float = 120.0):
    """Yield text deltas from NIM's SSE stream. Rolls to the next key on Transient."""
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(_nim_body(model, messages, max_tokens, temperature, True)).encode()

    def once(name: str, key: str):
        req = urllib.request.Request(url, data=data, headers=_nim_headers(key))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode(errors="replace").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[len("data: "):].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    for choice in (obj.get("choices") or []):
                        delta = choice.get("delta") or {}
                        text = delta.get("content") or delta.get("reasoning_content") or ""
                        if text:
                            yield text
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            if e.code == 429 or e.code >= 500:
                t = Transient(f"http {e.code} on {name}: {detail}")
                ra = e.headers.get("Retry-After") if e.code == 429 and e.headers else None
                t.retry_after = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
                raise t
            if e.code in (401, 403):
                t = Transient(f"http {e.code} on {name}: key rejected")
                t.retry_after = 3600.0
                raise t
            raise RuntimeError(f"http {e.code} on {name}: {detail}")
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            raise Transient(f"{type(e).__name__} on {name}: {e}")

    # stream across keys until one produces at least one delta
    last: Optional[Exception] = None
    used: Optional[str] = None
    attempts = max(2, len(pool.names))
    for attempt in range(attempts):
        try:
            with pool.lease(prefer=prefer if attempt == 0 else None, avoid=used) as name:
                used = name
                try:
                    yielded_any = False
                    with otel.span(
                        "router.llm.chat_stream",
                        {"llm.model": model, "llm.base_url": base_url, "llm.stream": True, "llm.key": name},
                    ):
                        for text in once(name, pool.value(name)):
                            yielded_any = True
                            yield text
                    if yielded_any:
                        pool.report(name, True)
                        return
                    pool.report(name, False)
                except Transient as e:
                    pool.report(name, False, retry_after=e.retry_after)
                    last = e
        except Transient as e:
            last = e
        time.sleep(backoff_s if False else 1.0)
    raise Transient(f"stream failed after {attempts} attempts: {last}")
