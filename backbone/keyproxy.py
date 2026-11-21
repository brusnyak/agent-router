"""Loopback key proxy for every discovered OpenAI-compatible provider (nim, groq, openrouter, ...).
Agents point base_url at http://127.0.0.1:PORT/v1 with a dummy key. The model field picks the provider:
  "auto" or a plain id            -> NIM (default model for "auto")
  "groq:<id>" / "openrouter:<id>" -> that provider, prefix stripped
Each provider has its own KeyPool: a key is leased per request, cooled on 429/5xx, and the request is retried on the
next key before any byte reaches the client. One jsonl log line per request (no bodies, no keys).
Real keys never appear in any agent's env, argv or config. `GET /health` lists providers and key state (no values)."""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("BACKBONE_KEYPROXY_PORT", "8790"))
LOG = os.path.expanduser("~/.agent-router/data/keyproxy.jsonl")


def build_pools(nim_cfg: dict) -> tuple:
    """-> ({provider: KeyPool}, {provider: base_url}). openai-style providers only; keys come from discovery (names only)."""
    import yaml
    from .keys import ENV_FILES, KeyPool, discover_keys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        known = yaml.safe_load(open(os.path.join(root, "config", "providers.yaml")))["providers"]
    except Exception:
        known = {"nim": {"base_url": nim_cfg["base_url"], "style": "openai"}}
    known = {p: v for p, v in known.items() if v.get("style", "openai") == "openai"}
    found = discover_keys(ENV_FILES, os.environ, known)
    pools, bases = {}, {}
    for prov, v in found.items():
        if not v["llm"] or not v["keys"] or prov not in known:
            continue
        names = list(dict.fromkeys((nim_cfg.get("keys") or []) + v["keys"])) if prov == "nim" else v["keys"]
        pool = KeyPool(names, rpm_limit=nim_cfg.get("rpm_limit", 40))
        if pool.names:
            pools[prov], bases[prov] = pool, known[prov]["base_url"]
    return pools, bases


def make_handler(pools: dict, bases: dict, default_model: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._json(200, {"ok": True, "providers": {p: pools[p].status() for p in pools}})
            else:
                self.fwd()

        def do_POST(self):
            self.fwd()

        def fwd(self):
            if not self.path.startswith("/v1/"):
                self.send_error(404, "use /v1/..."); return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            prov, model, stream = "nim", None, False
            if body:
                try:
                    j = json.loads(body); model = j.get("model"); stream = bool(j.get("stream"))
                    if model in ("auto", "router/auto", "", None):
                        j["model"] = model = default_model
                    elif isinstance(model, str) and ":" in model.split("/")[0] and model.split(":")[0] in pools:
                        prov, _, j["model"] = model.partition(":"); model = j["model"]
                    body = json.dumps(j).encode()
                except Exception:
                    pass
            pool = pools.get(prov)
            if pool is None:
                self.send_error(503, f"no keys for provider {prov}"); return
            u = urllib.parse.urlparse(bases[prov])
            path = u.path.rstrip("/") + self.path[len("/v1"):]
            conn_cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            t0, used, status, last = time.time(), None, 502, "no key available"
            for _ in range(max(1, len(pool.names))):
                try:
                    with pool.lease(avoid=used) as name:
                        used = name
                        c = conn_cls(u.netloc, timeout=600)
                        c.request(self.command, path, body or None,
                                  {"Authorization": f"Bearer {pool.value(name)}",
                                   "Content-Type": self.headers.get("Content-Type", "application/json"),
                                   "Content-Length": str(len(body))})
                        r = c.getresponse(); status = r.status
                        if status == 429 or status >= 500:
                            ra = r.getheader("Retry-After")
                            pool.report(name, False, retry_after=float(ra) if ra and ra.isdigit() else 30.0)
                            last = f"upstream {status}"; r.read(); continue
                        pool.report(name, True)
                        self.send_response(status)
                        if r.getheader("Content-Type"):
                            self.send_header("Content-Type", r.getheader("Content-Type"))
                        self.send_header("Connection", "close"); self.end_headers()
                        while True:
                            chunk = r.read(4096) if stream else r.read()
                            if not chunk:
                                break
                            self.wfile.write(chunk); self.wfile.flush()
                        break
                except Exception as e:  # Transient (no key free) or network error: try the next key
                    last = str(e)[:80]
            else:
                try:
                    self.send_error(503, last)
                except Exception:
                    pass
            try:
                os.makedirs(os.path.dirname(LOG), exist_ok=True)
                with open(LOG, "a") as f:
                    f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "provider": prov, "key": used,
                                        "path": self.path, "model": model, "status": status,
                                        "ms": int((time.time() - t0) * 1000),
                                        "ua": (self.headers.get("User-Agent") or "")[:40]}) + "\n")
            except Exception:
                pass

    return H


def serve(nim_cfg: dict, default_model: str, port: int = PORT) -> None:
    pools, bases = build_pools(nim_cfg)
    print(f"keyproxy on 127.0.0.1:{port}, providers: { {p: pools[p].names for p in pools} }", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(pools, bases, default_model)).serve_forever()
