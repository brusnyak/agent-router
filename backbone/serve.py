"""Loopback HTTP API so adapters (Telegram/WhatsApp bridges, Hermes, a future UI) can submit work and read status.
Same trust model as MCP: named gates, registered roots. Bearer token from BACKBONE_TOKEN is required."""
from __future__ import annotations

import hmac
import json
import os
import socket
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import nim
from . import otel
from . import status
from .jobs import Jobs
from .keys import Transient

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>agent router — dashboard</title>
<style>
  :root { --fg: #111; --muted: #666; --border: #ccc; --surface: #fafafa; --accent: #0b6; }
  * { box-sizing: border-box; }
  html { font: 13px/1.45 system-ui, -apple-system, sans-serif; color: var(--fg); }
  body { margin: 0; background: var(--surface); padding: 16px; }
  h1 { font-size: 16px; margin: 0 0 10px 0; letter-spacing: .3px; text-transform: uppercase; }
  .bar { display: flex; gap: 10px; align-items: baseline; margin-bottom: 6px; flex-wrap: wrap; }
  .bar b { font-size: 17px; }
  .tag { font-size: 11px; color: var(--muted); margin-left: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
  .card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
  .card h2 { font-size: 12px; margin: 0 0 8px 0; text-transform: uppercase; letter-spacing: .2px; color: var(--muted); border-bottom: 1px solid #eee; padding-bottom: 5px; }
  .kv { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; font-size: 13px; }
  .kv .k { color: var(--muted); }
  .runline { margin: 8px 0 0 0; font-size: 13px; font-variant-numeric: tabular-nums; }
  .runline span { margin-right: 12px; }
  .ok { color: var(--accent); } .bad { color: #c00; } .muted { color: var(--muted); }
  .workers { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
  .worker { border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 12px; min-width: 130px; }
  .worker .w { font-weight: 700; }
  .glyphs { margin-top: 4px; letter-spacing: 2px; font-variant-numeric: tabular-nums; }
  .g { margin-right: 4px; }
  .g.r { color: #ff9800; } .g.d { color: #0b6; } .g.b { color: #c00; } .g.q { color: #bbb; } .g.s { color: var(--muted); }
  .hosts { margin-top: 6px; }
  .host { margin: 4px 0; font-size: 12px; }
  .host .h { font-weight: 700; }
  .err { color: #c00; }
  .keys { margin-top: 8px; font-size: 12px; }
  .keys .k { display: inline-block; margin-right: 14px; }
  .keys .ok { font-weight: 700; }
  .keys .bad { color: #c00; font-weight: 700; }
  .refresh { font-size: 11px; color: var(--muted); margin-top: 8px; cursor: pointer; text-decoration: underline; }
  .refresh:hover { color: var(--fg); }
  .legend { font-size: 11px; color: var(--muted); margin: 8px 0 0 0; }
</style>
</head>
<body>
<h1>agent router</h1>
<div class="bar">
  <b id="ts">—</b>
  <span class="tag" id="host"></span>
</div>
<div class="grid">
  <div class="card">
    <h2>router</h2>
    <div class="kv">
      <div><span class="k">running</span> <b id="run">0</b></div>
      <div><span class="k">done (24h)</span> <b class="ok" id="done">0</b></div>
      <div><span class="k">failed</span> <b class="bad" id="failed">0</b></div>
      <div><span class="k">blocked (24h)</span> <b id="blocked">0</b></div>
      <div><span class="k">stale</span> <b class="bad" id="stale">0</b></div>
    </div>
  <div class="card hosts">
    <h2>hosts</h2>
    <div id="hosts">—</div>
  </div>
</div>
<div class="card">
  <h2>workers</h2>
  <div class="workers" id="workers">loading…</div>
  <div class="legend">glyphs: ● done · queued ◐ running ▫ blocked ✗ failed</div>
</div>
<div class="card keys">
  <h2>nim keys</h2>
  <div id="keys">loading…</div>
</div>
<div class="refresh" id="refresh">refresh</div>
<script>
async function load() {
  const res = await fetch("/status");
  const s = await res.json();
  document.getElementById("ts").textContent = new Date(s.ts * 1000).toLocaleString();
  const c = s.counts || {};
  document.getElementById("run").textContent = c.running || 0;
  document.getElementById("done").textContent = c.done || 0;
  document.getElementById("failed").textContent = c.failed || 0;
  document.getElementById("blocked").textContent = c.blocked || 0;
  document.getElementById("stale").textContent = s.stale_running || 0;
  const hosts = s.hosts || {};
  const hd = document.getElementById("hosts");
  hd.innerHTML = Object.entries(hosts).map(([h, v]) => {
    const bad = v.error || (v.age_s != null && v.age_s > 900);
    return `<div class="host"><span class="h">${escape(h)}</span> load ${v.load1 ?? "?"}/${v.cpus ?? "?"} mem ${v.mem_avail_mb ?? "?"}MiB age ${v.age_s ?? "?"}s${bad ? ' <span class="err">· error/stale</span>' : ""}</div>`;
  }).join("") || "no host snapshots";
  const wk = document.getElementById("workers");
  wk.innerHTML = Object.entries(s.workers || {}).map(([w, states]) => {
    const glyph = {"done": "●", "failed": "✗", "running": "◐", "blocked": "▫", "queued": "·"};
    const cls = {"done": "d", "failed": "b", "running": "r", "blocked": "▫".replace("▫","b"), "queued": "q"};
    const cls2 = {"done": "d", "failed": "b", "running": "r", "blocked": "b", "queued": "q"};
    const disp = w.replace("browser+", "b+").replace(":NIM_", ":n");
    return `<div class="worker"><div class="w">${escape(disp)}</div><div class="glyphs">${states.map(st => `<span class="g ${cls2[st] || 's'}">${glyph[st] || "?"}</span>`).join("")}</div></div>`;
  }).join("") || "no workers";
  const keys = document.getElementById("keys");
  const ks = await fetch("/keys").then(r => r.json()).catch(() => ({}));
  keys.innerHTML = Object.entries(ks || {}).map(([k, v]) => {
    const ok = v && v.ok != null && v.ok > 0;
    return `<span class="k ${ok ? "ok" : "bad"}">${escape(k)} ${ok ? "ok" : "idle/fail"}</span>`;
  }).join("") || "no key data";
}
function escape(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }
load();
document.getElementById("refresh").onclick = load;
setInterval(load, 10000);
</script>
</body>
</html>"""

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

        def _send_html(self, code: int, html: str) -> None:
            body = html.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
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
            if u.path == "/status":
                return self._send(200, status.collect())
            if u.path == "/keys":
                return self._send(200, bb.pool.status())
            if u.path == "/":
                return self._send_html(200, _DASHBOARD_HTML)
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
    root = os.path.expanduser("~/.agent-router")
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "router-daemon.pid"), "w") as f:
        f.write(str(os.getpid()))
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(bb, token)).serve_forever()
