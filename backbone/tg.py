"""Two-way Telegram for the daemon: readable job reports out, simple commands + free-text notes in.
Only messages from TELEGRAM_CHAT_ID are obeyed. Plain text is saved to data/telegram_inbox.md (never executed)."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from .notify import _cred, notify

NODE = os.environ.get("ROUTER_NODE") or os.uname().nodename.split(".")[0]
ICON = {"done": "✅", "blocked": "⛔", "failed": "❌"}
HELP = ("Commands:\n/status  daemon + jobs\n/jobs  last 8 jobs\n/show <id>  result of a job\n"
        "/run <prompt>  queue a job (runs on the hub); add @node:NAME to run on a node, e.g. /run @node:mac fix tests\n/nodes  which nodes are online\n/retry <id>  queue the same prompt again\n"
        "Any other text is saved as a note for the next Claude session.")


def report(job: dict, state: str, res: dict | None) -> str:
    out = str((res or {}).get("output") or (res or {}).get("error") or "").strip()
    out = "\n".join(l.strip() for l in out.splitlines() if l.strip())[:700]
    lines = [f"{ICON.get(state, '•')} {state.upper()} · {NODE} · job {job['id']}", "",
             f"Task: {job['text'][:140]}", "", "Result:", out or "(no output)", ""]
    rid = (res or {}).get("run")
    if rid:
        lines.append(f"Patch: ~/agent-router/data/runs/{rid}/patch.diff (review, then git apply)")
    if state != "done":
        lines.append(f"Next: /retry {job['id']}  or  /show {job['id']}")
    else:
        lines.append(f"Details: /show {job['id']}")
    return "\n".join(lines)


def _api(method: str, payload: dict, timeout: int = 35):
    tok = _cred("TELEGRAM_BOT_TOKEN")
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def _handle(jobs, text: str) -> str:
    cmd, _, arg = text.strip().partition(" ")
    arg = arg.strip()
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/status":
        rows = jobs.list(50)
        n = {s: sum(1 for r in rows if r["state"] == s) for s in ("pending", "running", "done", "blocked")}
        return f"{NODE} up · {n}"
    if cmd == "/jobs":
        return "\n".join(f"{ICON.get(r['state'], '•')} {r['id']} {r['state']} {r['text'][:50]}" for r in jobs.list(8)) or "no jobs"
    if cmd == "/show":
        r = jobs.bb.runs.get(next((j["run_id"] for j in jobs.list(50) if j["id"] == arg), "") or "")
        return (str((r or {}).get("output") or (r or {}).get("error") or "no result yet"))[:3500]
    if cmd == "/nodes":
        return "\n".join(f"{'🟢' if n['online'] else '⚫'} {n['name']} ({n['age_s']}s ago)" for n in jobs.nodes()) or "no nodes have connected"
    if cmd == "/run" and arg:
        return f"queued job {jobs.submit(arg)}"
    if cmd == "/retry":
        row = jobs.con.execute("SELECT text, opts FROM jobs WHERE id=?", (arg,)).fetchone()
        return f"queued job {jobs.submit(row['text'], **json.loads(row['opts'] or '{}'))}" if row else "unknown job id"
    path = os.path.join(os.path.dirname(jobs.bb.runs.runs_dir), "telegram_inbox.md")
    with open(path, "a") as f:
        f.write(f"- {time.strftime('%F %T')} {text.strip()}\n")
    return "saved as a note (not executed). /help for commands"


def poll_forever(jobs) -> None:
    chat, offset = str(_cred("TELEGRAM_CHAT_ID")), 0
    if not chat or not _cred("TELEGRAM_BOT_TOKEN"):
        return
    while True:
        try:
            for u in _api("getUpdates", {"offset": offset, "timeout": 25}, 35).get("result", []):
                offset = u["update_id"] + 1
                m = u.get("message") or {}
                if str(m.get("chat", {}).get("id")) == chat and m.get("text"):
                    notify(_handle(jobs, m["text"]))
        except Exception:
            time.sleep(10)


def start(jobs) -> None:
    if os.environ.get("ROUTER_TG_POLL") != "1":  # polling needs a bot nothing else polls (own bot via BotFather)
        return
    threading.Thread(target=poll_forever, args=(jobs,), daemon=True).start()
