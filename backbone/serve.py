"""Loopback HTTP API so adapters (Telegram/WhatsApp bridges, Hermes, a future UI) can submit work and read status.
Same trust model as MCP: named gates, registered roots. Bearer token from BACKBONE_TOKEN is required."""
from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import nim
from . import otel
from .jobs import Jobs
from .keys import Transient


def make_handler(bb, token: str):
    jobs = Jobs(bb)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, obj) -> None:
            body = json.dumps(obj, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self) -> bool:
            got = self.headers.get("Authorization", "")
            if not hmac.compare_digest(got, f"Bearer {token}"):
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self._auth():
                return
            u = urlparse(self.path)
            if u.path == "/nodes":
                return self._send(200, jobs.nodes())
            if u.path.startswith("/jobs/"):
                j = jobs.get(u.path.split("/")[2])
                return self._send(200 if j else 404, j or {"error": "not found"})
            if u.path == "/jobs":
                return self._send(200, jobs.list())
            if u.path.startswith("/runs/"):
                rid = u.path.split("/")[2]
                return self._send(200, {"run": bb.runs.get(rid), "steps": bb.runs.steps(rid)})
            if u.path == "/library":
                q = parse_qs(u.query).get("q", [""])[0]
                return self._send(200, bb.rag.search(q, k=5))
            if u.path == "/keys":
                return self._send(200, bb.pool.status())
            self._send(404, {"error": "not found"})

        def _sse(self, obj) -> None:
            self.wfile.write(f"data: {json.dumps(obj, default=str)}\n\n".encode())
            self.wfile.flush()

        def _chat_completions(self, d: dict) -> None:
            model = d.get("model") or bb.cfg["nim"]["model"]
            messages = d.get("messages") or []
            if not isinstance(messages, list) or not messages:
                return self._send(400, {"error": "messages must be a non-empty list"})
            stream = bool(d.get("stream"))
            max_tokens = int(d.get("max_tokens") or 1500)
            temperature = float(d.get("temperature") or 0.2)
            prefer = d.get("user")  # carried through as the key preference hint (not used for routing)
            created = int(time.time())
            cid = f"chatcmpl-{uuid.uuid4().hex[:16]}"

            n = bb.cfg["nim"]
            if not stream:
                try:
                    text = nim.chat(bb.pool, messages, base_url=n["base_url"], model=n["model"],
                                    max_tokens=max_tokens, temperature=temperature, prefer=prefer)
                except Exception as e:
                    return self._send(502, {"error": f"completion failed: {type(e).__name__}: {e}"})
                self._send(200, {
                    "id": cid, "object": "chat.completion", "created": created, "model": model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                 "finish_reason": "stop"}],
                })
                return

            def send(obj) -> None:
                self._sse(obj)

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                send({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                      "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
                for text in nim.chat_stream(bb.pool, messages, base_url=bb.cfg["nim"]["base_url"],
                                            model=model, max_tokens=max_tokens,
                                            temperature=temperature, prefer=prefer):
                    send({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                          "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})
                send({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                      "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                send({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                      "choices": []})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Transient as e:
                try:
                    self._sse({"error": f"stream failed: {e}"})
                except Exception:
                    pass
            except Exception as e:
                try:
                    self._sse({"error": f"stream error: {type(e).__name__}: {e}"})
                except Exception:
                    pass

        def do_POST(self):
            if not self._auth():
                return
            path = urlparse(self.path).path
            allowed = ("/submit", "/nodes/claim", "/nodes/result", "/v1/chat/completions")
            if path not in allowed:
                return self._send(404, {"error": "not found"})
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if path == "/nodes/claim":
                    return self._send(200, {"job": jobs.claim_for_node(str(d["node"]), d.get("caps") or {})})
                if path == "/nodes/result":
                    return self._send(200, {"ok": jobs.finish_from_node(str(d["node"]), str(d["job"]), str(d.get("state", "blocked")),
                                                                        str(d.get("output", "")), str(d.get("run", "")))})
                if path == "/v1/chat/completions":
                    return self._chat_completions(d)
                opts = {}
                if d.get("gate"):
                    bb.named_gate(d["gate"])  # validate the name against the hub config
                    opts["gate_name"] = d["gate"]  # nodes re-resolve the NAME against their own config; raw commands never travel
                    if not str(d.get("text", "")).count("@node:") and not d.get("target"):
                        opts["gate"] = bb.named_gate(d["gate"])
                if d.get("cwd"):
                    opts["cwd"] = bb.check_cwd(d["cwd"])
                for k in ("project", "worker", "target"):
                    if d.get(k):
                        opts[k] = d[k]
                self._send(200, {"job": jobs.submit(str(d["text"]), **opts)})
            except PermissionError as e:
                self._send(403, {"error": str(e)})
            except (KeyError, ValueError) as e:
                self._send(400, {"error": f"bad request: {e}"})

    return H


def serve(bb, port: int = 8799) -> None:
    token = os.environ.get("BACKBONE_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("set BACKBONE_TOKEN (>=16 chars) before serving")
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(bb, token)).serve_forever()
