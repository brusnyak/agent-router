#!/usr/bin/env python3
"""Idle-gated practice-mode tick (Mac). Runs from launchd every 10 min; does nothing unless ALL hold:
owner idle >= 10 min, no router run in flight, load < 4, last tick >= 30 min ago, < 8 ticks today, not paused.
One READY auto-safe task from the ROI queue per tick, executed by `backbone run @pi --read-only` (read tool only:
no shell, no write, no send, no spend). The receipt is written by this script into the vault, never by the worker.
Receipts: ~/vault/pages/reports/practice/ (INDEX.md = one line per tick). Stdlib only."""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
VAULT = os.path.expanduser(os.environ.get("BACKBONE_VAULT", "~/vault"))
QUEUE = f"{VAULT}/pages/plans/2026-11-19-roi-execution-queue.md"
PROMPT = f"{VAULT}/pages/prompts/agent-router-practice-mode-operator.md"
OUT = f"{VAULT}/pages/reports/practice"
STATE = f"{HOME}/.agent-router/data/idle_practice.json"
IDLE_S, GAP_S, MAX_DAY, MAX_TRIES = 600, 1800, 8, 2


def idle_seconds() -> float:
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


def load_state() -> dict:
    try:
        return json.load(open(STATE))
    except Exception:
        return {"last": 0, "day": "", "n": 0, "tries": {}}


def ready_tasks() -> list:
    text = open(QUEUE, encoding="utf-8").read()
    tasks = []
    for block in re.split(r"(?m)^### ", text)[1:]:
        tid = block.split("\n", 1)[0].strip()
        f = dict(re.findall(r"(?m)^(\w[\w-]*)::\s*(.*)$", block))
        risk = f.get("risk", "")
        if f.get("state", "").strip() == "READY" and "auto-safe" in risk and "gated" not in risk:
            tasks.append((tid, "### " + block.strip()))
    return tasks


def main() -> int:
    log = lambda m: print(time.strftime("%F %T"), m, flush=True)
    st, now = load_state(), time.time()
    today = dt.date.today().isoformat()
    if st.get("day") != today:
        st.update(day=today, n=0)
    if idle_seconds() < IDLE_S:
        return log("skip: owner active") or 0
    if now - st["last"] < GAP_S or st["n"] >= MAX_DAY:
        return log("skip: gap/day cap") or 0
    if os.getloadavg()[0] >= 4:
        return log("skip: load") or 0
    if subprocess.run(["pgrep", "-f", "backbone run"], capture_output=True).stdout.strip():
        return log("skip: a router run is in flight") or 0
    tasks = [t for t in ready_tasks() if st["tries"].get(t[0], 0) < MAX_TRIES]
    if not tasks:
        return log("skip: no READY auto-safe task with tries left") or 0
    tid, body = min(tasks, key=lambda t: st["tries"].get(t[0], 0))  # least-tried first
    st["tries"][tid] = st["tries"].get(tid, 0) + 1
    st["last"], st["n"] = now, st["n"] + 1
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"))
    packet = (open(PROMPT, encoding="utf-8").read() + "\n\nCHOSEN TASK (execute only this):\n" + body +
              "\n\nLANE LIMITS: you have a read tool only (no shell, no write, no browsing). Read files under "
              "~/vault and ~/Developer. Cite file paths for every claim. If the task needs a tool you lack, "
              "reply RESULT: blocked and name the exact missing capability. Use at most 12 read calls, then answer: "
              "converge, do not keep exploring. Answer with the receipt fields only.")
    try:
        p = subprocess.run(["backbone", "run", "--no-vault", "--read-only", "@pi", packet], capture_output=True,
                           text=True, timeout=700, cwd=HOME)
        d = json.loads(p.stdout[p.stdout.index("{"):])
        out, state = d.get("output", ""), d.get("state", "?")
    except Exception as e:
        out, state = f"runner error: {e}", "error"
    m = re.search(r"(?m)^\s*RESULT:\s*(done|blocked|partial)\b", out, re.I) if state == "done" else None
    result = m.group(1).lower() if m else ("error" if state != "done" else "malformed")
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M")
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{ts}-{tid}.md"
    open(path, "w", encoding="utf-8").write(
        f"type:: [[report]]\narea:: [[Ops]]\nstatus:: UNVERIFIED worker receipt (pi read-only, router state={state})\n\n"
        f"# Practice tick {ts}: {tid}\n\nRESULT(parsed): {result}\n\n{out}\n")
    with open(f"{OUT}/INDEX.md", "a", encoding="utf-8") as fh:
        if os.path.getsize(f"{OUT}/INDEX.md") == 0:
            fh.write("type:: [[report]]\narea:: [[Ops]]\n\n# Practice mode receipts (newest last; all UNVERIFIED until a human or gate checks)\n\n")
        fh.write(f"- {ts} {tid} -> {result} ({state}) [[{os.path.basename(path)[:-3]}]]\n")
    log(f"ran {tid}: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
