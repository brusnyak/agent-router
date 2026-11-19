"""LangGraph run graph with a SQLite checkpointer.

prepare -> work -> check -> (work again | finish). Each node boundary is checkpointed per run id, so a crashed
process resumes at the next node (`resume(run_id)`) instead of repeating completed steps. Loop-vs-single is decided
in `prepare` (a gate means a loop); the loop is graph edges, not a Python `for`.
"""
from __future__ import annotations

import dataclasses
import sqlite3
import threading
import uuid
import time
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from .evidence import missing_paths
from .runs import StaleLease
from .workers import Result
from .workspace import IsolationError, Workspace, run_gate


class S(TypedDict, total=False):
    rid: str
    text: str
    opts: dict
    sid: str
    task_prompt: str
    project: str
    proj_path: str
    ws_path: str
    ws_base: str
    isolated: bool
    spec: str
    plan: List[str]
    n: int
    sources: list
    gate: Optional[str]
    read_only: bool
    style: str
    mode: str
    packet: str
    feedback: str
    last: dict
    gate_out: str
    verified: bool
    accepted: bool
    abort: bool
    out: dict
    started_at: float


def build(bb, db_path: str):
    from .core import norm_worker, parse  # local import: core imports this module lazily

    gcon = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    gcon.execute("PRAGMA journal_mode=WAL")
    gcon.execute("PRAGMA busy_timeout=30000")
    saver = SqliteSaver(gcon)
    beats: Dict[str, threading.Event] = {}
    fences: Dict[str, int] = {}  # epoch this process owns for each run

    def start_beat(rid: str) -> None:
        if rid in beats:
            return
        ev = threading.Event()
        beats[rid] = ev
        fences[rid] = bb.runs.fence(rid)

        def beat():
            while not ev.wait(20):
                if not bb.runs.heartbeat(rid, fences[rid]):
                    break  # reaped: stop reviving the lease

        threading.Thread(target=beat, daemon=True).start()

    def stop_beat(rid: str) -> None:
        ev = beats.pop(rid, None)
        if ev:
            ev.set()

    def ws_of(s: S) -> Workspace:
        return Workspace.attach(s["proj_path"], s["ws_path"], s.get("ws_base", ""), s.get("isolated", False))

    def prepare(s: S) -> dict:
        o = s["opts"]
        task = parse(s["text"])
        task.project = o.get("project") or task.project
        spec = norm_worker(o.get("worker") or task.worker)
        # Non-binary workers (e.g. openhands over HTTP) are configured by base_url, not a PATH binary.
        # Preserve them as-is: never let norm_worker or a fallback swap them for a local binary.
        if spec and not bb.cfg.get("workers", {}).get(spec, {}).get("base_url"):
            spec = norm_worker(spec)
        # Approved scheduler packets already name their sources and worker. Avoid
        # another model/retrieval pass; normal chat keeps the existing resolver.
        if o.get("prepared") and spec:
            prompt, meta, notes, sources = task.prompt, {}, "", []
        else:
            prompt, meta, notes, sources = bb.resolve(task)
        spec = spec or norm_worker(meta.get("worker", "")) or f"pi:{bb.cfg['nim']['default_key']}"
        gate = o.get("gate") or meta.get("gate") or None
        read_only = bool(o.get("read_only")) or str(meta.get("readonly", "")).lower() in ("1", "true", "yes")
        esc = o["escalate"] if o.get("escalate") is not None else meta.get(
            "escalate", bb.cfg.get("escalation", {}).get("expert", ""))
        sid = bb.sessions.open(o.get("session"), task.project)
        bb.sessions.add_turn(sid, "user", task.prompt)
        proj_path = bb.project_path(task.project, o.get("cwd"))
        pinned = ""
        proj = bb.projects.get(task.project or "")
        if proj:
            pinned = f"Project {proj.get('name', proj['id'])} at {proj_path}. Type: {proj.get('type', '')}."
        style = str(meta.get("style") or bb.cfg.get("style", {}).get("default", "caveman"))
        st = bb.cfg.get("style", {}).get("texts", {}).get(style, "")
        if st:
            pinned = (pinned + "\n" if pinned else "") + "Output style: " + st
        # Private vault notes only go to workers the owner is logged into themselves (config `vault_to`); never to free API tiers.
        vault_ok = spec.split(":")[0] in bb.cfg.get("vault_to", ["claude", "codex"])
        packet = bb.sessions.pack(sid, prompt, pinned=pinned, library_notes=notes, use_vault=bool(o.get("use_vault", True)) and vault_ok)
        rid = s["rid"]
        bb.runs.create(sid, task.project, task.command, task.prompt, spec, {"gate": gate, "esc": esc, "sources": sources}, rid=rid)
        cb = bb._on_start.pop(rid, None)
        if cb:
            cb(rid)  # durable run<->job link before any side effect
        try:
            ws = Workspace(proj_path, rid, bb.work_root, isolate=o.get("isolate", True) and not read_only)
        except IsolationError as e:
            bb.runs.set(rid, "failed", error=str(e))
            return {"abort": True, "out": {"run": rid, "session": sid, "state": "failed", "error": str(e), "ticket": ""}}
        loop = bool(gate) and not read_only
        plan = ([spec, spec] + ([norm_worker(esc)] if esc and norm_worker(esc) != spec else [])) if loop else [spec]
        bb._hook("pre_run", rid, mode="loop" if loop else "single", worker=spec, style=style)
        return {"sid": sid, "task_prompt": task.prompt, "project": task.project, "proj_path": proj_path,
                "ws_path": ws.path, "ws_base": ws.base, "isolated": ws.isolated, "spec": spec, "plan": plan, "n": 0,
                "gate": gate, "read_only": read_only, "style": style, "mode": "loop" if loop else "single",
                "packet": packet, "feedback": "", "abort": False, "sources": sources,
                "started_at": time.time()}

    def work(s: S) -> dict:
        rid, n = s["rid"], s["n"]
        start_beat(rid)
        prompt = s["packet"] + (f"\n\n## Previous attempt failed the acceptance check\n{s['feedback']}\nFix it."
                                if s.get("feedback") else "")
        r = bb._dispatch(s["plan"][n], prompt, s["ws_path"], s["read_only"], n + 1)
        bb.runs.step(rid, n + 1, "work", r.worker, r.key_slot, r.ok, r.latency_ms, r.text, fence=fences.get(rid))
        if not bb.runs.set(rid, "running", worker=r.worker, attempt=n + 1, fence=fences.get(rid)):
            raise StaleLease(f"run {rid}: lease was reaped; stale worker write rejected")
        return {"last": dataclasses.asdict(r)}

    def check(s: S) -> dict:
        rid, n, last = s["rid"], s["n"], s["last"]
        if not last["ok"]:
            return {"accepted": False, "feedback": f"worker error: {last['text'][:500]}", "n": n + 1}
        if s.get("gate"):
            ok, out = run_gate(s["gate"], s["ws_path"])
            bb.runs.step(rid, n + 1, "gate", "router", "", ok, 0, out, fence=fences.get(rid))
            if ok:
                return {"accepted": True, "verified": True, "gate_out": out, "n": n + 1}
            return {"accepted": False, "feedback": out[-800:], "gate_out": out, "n": n + 1}
        return {"accepted": True, "verified": False, "n": n + 1}

    def critic(s: S) -> dict:
        """Skepticism layer: a free OpenRouter model re-reviews accepted output against the task.
        verified=false blocks done; config-driven via `critic.when` (always|gate|opinion, default gate).
        Skipped when OPENROUTER_API_KEY is not set (leaves verified unchanged)."""
        from .critic import critique
        import os
        when = str(bb.cfg.get("critic", {}).get("when", "gate")).lower()
        gate_present = bool(s.get("gate"))
        read_only = bool(s.get("read_only"))
        run = (when == "always") or (when == "gate" and gate_present) or (when == "opinion" and read_only)
        if not run or not os.environ.get("OPENROUTER_API_KEY"):
            return {"verified": bool(s.get("verified"))}
        task = s.get("task_prompt") or s["text"]
        last = s["last"]
        c = critique(lambda m: bb.chat(m, max_tokens=600), task, last.get("text", ""),
                     diff=s.get("patch", "") or "", gate_out=s.get("gate_out", ""))
        verdict = c.get("verdict", "unknown")
        verified = bool(s.get("verified")) and verdict == "pass"
        issues = c.get("issues", [])
        feedback = "; ".join(i.get("claim", "") for i in issues[:3]) if issues else ""
        return {"verified": verified, "feedback": (s.get("feedback", "") + ("\nCritic: " + feedback if feedback else "")).strip(),
                "critic_verdict": verdict, "critic_issues": issues}

    def after_check(s: S) -> str:
        if s.get("accepted"):
            return "critic"
        last = s.get("last", {})
        if not last.get("ok"):
            meta = last.get("meta") or {}
            text = str(last.get("text", "")).lower()
            if (meta.get("retryable") is False or meta.get("failure_kind") == "timeout"
                    or "timeout after" in text or "timed out" in text
                    or text.startswith("blocked:")):
                return "finish"
        return "work" if s["n"] < len(s["plan"]) else "finish"

    def after_critic(s: S) -> str:
        if s.get("verified"):
            return "finish"
        return "work" if s["n"] < len(s["plan"]) else "finish"

    def finish(s: S) -> dict:
        rid, last = s["rid"], s["last"]
        ws = ws_of(s)
        success = bool(last["ok"] and s["accepted"])
        diff = ws.diff()
        patch = bb.runs.save_patch(rid, diff) if diff else ""
        reason = ""
        ticket = ""
        if success:
            if not bb.runs.set(rid, "done", fence=fences.get(rid)):
                raise StaleLease(f"run {rid}: lease was reaped; 'done' from a stale worker rejected")
        else:
            reason = (s.get("gate_out") or last["text"])[:400]
            ticket = bb.runs.ticket(rid, reason, "retry with a smaller scope or a different worker/key; read the last steps first")
            if not bb.runs.set(rid, "blocked", error=reason, fence=fences.get(rid)):
                raise StaleLease(f"run {rid}: lease was reaped; 'blocked' from a stale worker rejected")
        bb.sessions.add_turn(s["sid"], "assistant", last["text"][:4000])
        try:
            bb.sessions.maybe_fold(s["sid"], bb.summarize)
        except Exception:
            pass
        from .evidence import missing_paths
        miss = missing_paths(last["text"], [s["ws_path"], s["proj_path"]]) if last["ok"] else []  # before cleanup: the worktree still holds files the worker just wrote
        # web + file verification: cited URLs readable, cited files exist, claims supported
        try:
            from .verify import verify_output
            evidence_ok, vreasons = verify_output(last["text"], [s["ws_path"], s["proj_path"]])
        except Exception:
            evidence_ok, vreasons = True, []
        gate_passed = bool(s.get("verified")) and evidence_ok
        verified = gate_passed and not miss
        reason = "" if verified else (f"cites_missing_file: {', '.join(miss[:5])}" if miss else ("no gate" if not s.get("gate") else "gate failed"))
        if not evidence_ok:
            reason = (reason + "; " if reason else "") + "; ".join(vreasons[:3])
        # record outcome for per-class/route learning (gate result is the only training signal)
        try:
            con = bb.con._c
            con.execute("INSERT INTO outcomes (run_id, task_class, route, ok, latency_ms, cost, evidence_ok, verified) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (s["rid"], s.get("task_class", ""), last["worker"], int(success), last["latency_ms"], 0.0,
                         int(bool(s.get("evidence_ok"))), int(bool(s.get("verified")))))
            con.commit()
        except Exception:
            pass
        from .plan import learn
        learn(s.get("task_prompt") or s["text"], last["worker"], bool(s.get("gate")), gate_passed, last["latency_ms"])
        return {"out": {"run": rid, "session": s["sid"], "state": "done" if success else "blocked", "worker": last["worker"],
                        "mode": s["mode"], "style": s["style"], "verified": verified,
                        "key_slot": last.get("key_slot", ""), "worker_meta": last.get("meta", {}),
                        "elapsed_ms": max(0, round((time.time() - s.get("started_at", time.time())) * 1000)),
                        "gate_passed": gate_passed, "evidence_missing": miss, "unverified_reason": reason,
                        "attempts": s["n"], "output": last["text"], "gate_output": s.get("gate_out", ""), "patch": patch,
                        "ticket": ticket, "workspace": s["ws_path"] if s["isolated"] else s["proj_path"], "prompt_sources": s.get("sources", []),
                        "latency_ms": last["latency_ms"]}}

    g = StateGraph(S)
    g.add_node("prepare", prepare)
    g.add_node("work", work)
    g.add_node("check", check)
    g.add_node("critic", critic)
    g.add_node("finish", finish)
    g.add_edge(START, "prepare")
    g.add_conditional_edges("prepare", lambda s: END if s.get("abort") else "work", {END: END, "work": "work"})
    g.add_edge("work", "check")
    g.add_conditional_edges("check", after_check, {"finish": "finish", "work": "work", "critic": "critic"})
    g.add_conditional_edges("critic", after_critic, {"finish": "finish", "work": "work"})
    g.add_edge("finish", END)
    compiled = g.compile(checkpointer=saver)
    compiled.stop_beat = stop_beat  # type: ignore[attr-defined]
    return compiled
