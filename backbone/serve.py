"""Loopback HTTP API so adapters (Telegram/WhatsApp bridges, Hermes, a future UI) can submit work and read status.
Same trust model as MCP: named gates, registered roots. Bearer token from BACKBONE_TOKEN is required."""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .jobs import Jobs


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

        def do_POST(self):
            if not self._auth():
                return
            if urlparse(self.path).path != "/submit":
                return self._send(404, {"error": "not found"})
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                opts = {}
                if d.get("gate"):
                    opts["gate"] = bb.named_gate(d["gate"])
                if d.get("cwd"):
                    opts["cwd"] = bb.check_cwd(d["cwd"])
                for k in ("project", "worker"):
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
