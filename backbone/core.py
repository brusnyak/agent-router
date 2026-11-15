"""Backbone: parse -> resolve library -> pack context -> dispatch -> router-run gate -> escalate -> ticket.

Grammar (leading tokens only, any order):  [/command] [#project] [@worker] prompt
  /command  a library row of kind 'command' (data, ingestable); unknown names fall back to library search
  #project  id from config/projects.yaml
  @worker   nim1|nim2|nim3 (Pi on that NIM key), claude, codex
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import yaml

from . import library, nim, otel
from .context import Sessions, est_tokens
from .db import connect
from .keys import KeyPool, Transient
from .runs import Runs, StaleLease
from .workers import ClaudeWorker, AgyWorker, CodexWorker, GooseWorker, JcodeWorker, OpenHandsWorker, OpencodeWorker, PiWorker, Result
from .workspace import IsolationError, Workspace, run_gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOKEN = re.compile(r"^([/#@])([A-Za-z0-9_.:-]+)\s*")


@dataclass
class Task:
    prompt: str
    command: str = ""
    project: str = ""
    worker: str = ""


def parse(text: str) -> Task:
    t = Task(prompt=text.strip())
    while True:
        m = _TOKEN.match(t.prompt)
        if not m:
            break
        sigil, val = m.groups()
        if sigil == "/" and not t.command:
            t.command = val
        elif sigil == "#" and not t.project:
            t.project = val
        elif sigil == "@" and not t.worker:
            t.worker = val
        else:
            break
        t.prompt = t.prompt[m.end():]
    return t


def norm_worker(w: str) -> str:
    w = (w or "").strip()
    m = re.fullmatch(r"nim(\d)?", w, re.I)
    if m:
        return f"pi:NIM_{m.group(1) or 1}"
    if w.lower() == "pi":
        return "pi:NIM_1"
    if w.lower().startswith("host:"):
        return w
    if w.lower() == "browser":
        return "browser"
    m = re.fullmatch(r"(jcode|opencode)(?::?(?:nim|NIM_)(\d))?", w, re.I)
    if m:
        return f"{m.group(1).lower()}:NIM_{m.group(2) or 1}"
    if w.lower() == "agy":
        return "agy"
    if w.lower() == "or" or w.lower().startswith("or:"):
        return "or:" + (w.split(":", 1)[1] if ":" in w else "")
    return w


def nimcfg_default(bb) -> str:
    return bb.cfg["nim"]["default_key"]


def resolve_worker(text_worker: str, flag_worker: str) -> tuple:
    """(worker spec, error). `--worker X` with `@host:H` in the text means: run X on H; a different remote worker is a conflict."""
    tw, fw = norm_worker(text_worker), norm_worker(flag_worker)
    if tw.lower().startswith("host:") and fw and not fw.lower().startswith("host:"):
        name, _, rw = tw[5:].partition(":")
        if rw and norm_worker(rw) != fw:
            return "", f"conflict: text says {tw} but --worker says {flag_worker}; give one"
        return f"host:{name}:{flag_worker}", ""
    return (fw or tw), ""


def load_config(path: Optional[str] = None) -> dict:
    user = os.path.expanduser("~/.agent-router/backbone.yaml")
    path = path or (user if os.path.exists(user) else os.path.join(ROOT, "config", "backbone.yaml"))
    with open(path) as f:
        return yaml.safe_load(f)


def swarm_cap(n, max_workers: int, rpm_limit: int, n_keys: int) -> int:
    """Worker cap. Explicit numeric n wins; None/'auto' -> max_workers, never above rpm_limit x keys."""
    if n not in (None, "auto"):
        return int(n)
    return max(1, min(max_workers, rpm_limit * n_keys) if n_keys else max_workers)


class Backbone:
    def __init__(self, cfg: Optional[dict] = None, env: Optional[dict] = None):
        self.cfg = cfg or load_config()
        base = ROOT
        rel = lambda p: os.path.expanduser(p) if os.path.isabs(os.path.expanduser(p)) else os.path.join(base, p)
        self.con = connect(rel(self.cfg["db"]))
        n = self.cfg["nim"]
        self.pool = KeyPool(n["keys"], max_concurrent=n.get("max_concurrent_per_key", 0),
                            cooldown_s=n.get("cooldown_s", 0), rpm_limit=n.get("rpm_limit", 40), env=env, wait_s=n.get("wait_s", 120))
        self.sessions = Sessions(self.con, self.cfg.get("context", {}))
        self.runs = Runs(self.con, rel(self.cfg["tickets_dir"]), rel(self.cfg.get("runs_dir", "data/runs")))
        self.work_root = rel(self.cfg.get("work_dir", "data/work"))
        w = self.cfg.get("workers", {})
        self.pi = PiWorker(w.get("pi", {}), n["model"])
        self.goose = GooseWorker(w.get("goose", {}), n["model"])
        self.openhands = OpenHandsWorker(w.get("openhands", {}))
        self.claude = ClaudeWorker(w.get("claude", {}))
        self.codex = CodexWorker(w.get("codex", {}))
        self.jcode = JcodeWorker(w.get("jcode", {}), n["model"])
        self.opencode = OpencodeWorker(w.get("opencode", {}), n["model"], ROOT)
        self.agy = AgyWorker(w.get("agy", {}), ROOT)
        self.projects = self._load_projects(rel(self.cfg.get("projects_file", "config/projects.yaml")))
        self._expert_lock = threading.Lock()  # SPEC D5: one expert (own-login) process at a time
        self._on_start: Dict[str, Callable[[str], None]] = {}
        from .graph import build
        self.graph = build(self, rel(self.cfg.get("graph_db", "data/graph.db")))
        from .rag import Rag
        self.rag = Rag(self.con, self.pool, n)

    # -- registry -------------------------------------------------------
    @staticmethod
    def _load_projects(path: str) -> Dict[str, dict]:
        try:
            d = yaml.safe_load(open(path)) or {}
        except OSError:
            return {}
        return {p["id"]: p for p in d.get("projects", []) if p.get("id")}

    def project_path(self, project: str, cwd: Optional[str]) -> str:
        if cwd:
            return os.path.expanduser(cwd)
        p = self.projects.get(project or "")
        return os.path.expanduser(p["path"]) if p and p.get("path") else os.getcwd()

    def _hook(self, event: str, rid: str, **kv) -> None:
        """config `hooks: {pre_run: [cmd,...], post_run: [...]}`: trusted owner config, run with RUN_ID/EVENT/k=v env."""
        for cmd in self.cfg.get("hooks", {}).get(event, []) or []:
            try:
                env = {**os.environ, "RUN_ID": rid, "EVENT": event, **{k.upper(): str(v) for k, v in kv.items()}}
                subprocess.run(cmd, shell=True, env=env, timeout=30, capture_output=True, stdin=subprocess.DEVNULL)
            except Exception:
                pass  # hooks never break a run

    def watch_once(self, repos: Optional[List[str]] = None, base: str = "~/Developer/refs") -> dict:
        """Poll GitHub for new commits; pull the local clone, re-ingest and embed what changed."""
        from .watch import changed
        out = {}
        for repo in repos or self.cfg.get("watch", {}).get("repos", []):
            if changed(self.con._c, repo):
                d = os.path.join(os.path.expanduser(base), repo.replace("/", "_"))
                if os.path.isdir(d):
                    subprocess.run(["git", "-C", d, "pull", "-q", "--ff-only"], timeout=120, capture_output=True)
                out[repo] = "changed"
        if out:
            self.ingest()
            self.rag.embed_missing()
        return out

    def allowed_roots(self) -> List[str]:
        roots = [os.path.realpath(os.path.expanduser(p["path"])) for p in self.projects.values() if p.get("path")]
        roots += [os.path.realpath(os.path.expanduser(r)) for r in self.cfg.get("allowed_roots", [])]
        return roots

    def check_cwd(self, cwd: str) -> str:
        """Model-supplied cwd must live under a registered project or an allowed root."""
        real = os.path.realpath(os.path.expanduser(cwd))
        if not any(real == r or real.startswith(r + os.sep) for r in self.allowed_roots()):
            raise PermissionError(f"cwd {real} is outside registered projects/allowed_roots")
        return real

    def named_gate(self, name: str) -> str:
        """Model-supplied gates are names from config `gates:`; raw shell strings are CLI-only."""
        g = self.cfg.get("gates", {}).get(name)
        if not g:
            raise PermissionError(f"unknown gate '{name}'; known: {sorted(self.cfg.get('gates', {}))}")
        return g

    def ingest(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for src in self.cfg.get("library", {}).get("sources", []):
            out[src["path"] + (":" + src["prefix"] if src.get("prefix") else "") + (":" + src["match"] if src.get("match") else "")] = library.ingest_dir(self.con, src["path"], src["kind"], prefix=src.get("prefix", ""), match=src.get("match", ""))
        return out

    # -- llm helpers ----------------------------------------------------
    def chat(self, messages: List[dict], max_tokens: int = 1500, prefer: str = "NIM_1") -> str:
        n = self.cfg["nim"]
        return nim.chat(self.pool, messages, base_url=n["base_url"], model=n["model"], max_tokens=max_tokens,
                        prefer=prefer, retries=n.get("retries", 1), backoff_s=n.get("backoff_s", 3))

    def summarize(self, text: str) -> str:
        return self.chat([{"role": "user", "content": text}], max_tokens=800)

    # -- library resolution --------------------------------------------
    def retrieve(self, text: str, kind: Optional[str] = None, k: int = 3) -> list:
        """Goal understanding by the model: expand the request, retrieve hybrid, let the model reason over candidates.
        Measured on 67 queries: top1 0.69 -> 0.88, top3 0.85 -> 0.97 vs plain hybrid (evalset)."""
        if not self.cfg.get("understand", True):
            return self.rag.search(text, kind, k)
        from . import understand
        llm = lambda m: self.chat(m, max_tokens=500)
        hits = self.rag.search(text[:1500] + " " + understand.expand(llm, text), kind, 10)
        return understand.rerank(llm, text, hits, k=k)[:k]

    def resolve(self, task: Task) -> tuple[str, dict, str, list]:
        """Return (prompt_with_template, command_meta, library_notes)."""
        meta: dict = {}
        sources: list = []  # provenance: which library rows shaped this prompt (id, kind, name, how)
        prompt = task.prompt
        if task.command:
            row = library.get(self.con, "command", task.command) or library.get(self.con, "skill", task.command)
            if not row:
                hits = library.search(self.con, task.command.replace("-", " ") + " " + task.prompt, k=1)
                row = hits[0] if hits else None
                if row:
                    row = library.get(self.con, row["kind"], row["name"])
            if row:
                sources.append({"id": row["id"], "kind": row["kind"], "name": row["name"], "how": "command-template"})
                meta = row["meta"]
                body = row["body"].strip()
                prompt = body.replace("$ARGUMENTS", task.prompt).replace("{prompt}", task.prompt) \
                    if ("$ARGUMENTS" in body or "{prompt}" in body) else f"{body}\n\nTask: {task.prompt}"
            else:
                prompt = f"/{task.command} {task.prompt}"
        hits = self.retrieve(task.prompt, k=3)
        notes = "\n".join(f"- {h['kind']}:{h['name']} - {h['description'][:140]}" for h in hits)
        # A strong hit (found by both BM25 and embeddings, near the top) contributes its actual instructions, not just a name.
        inj = self.cfg.get("inject", {})
        used = {s["id"] for s in sources}
        for h in hits[: int(inj.get("max_bodies", 1))]:
            if h["id"] in used or h["kind"] == "command":
                continue
            if h["via"] == "both" and h["score"] >= float(inj.get("min_score", 0.028)):
                row = library.get(self.con, h["kind"], h["name"])
                if row and row["body"].strip():
                    clip = row["body"].strip()[: int(inj.get("max_chars", 1500))]
                    notes += f"\n\n### Instructions from {h['kind']} '{h['name']}' (follow where relevant)\n{clip}"
                    sources.append({"id": h["id"], "kind": h["kind"], "name": h["name"], "how": "body-injected", "score": h["score"]})
        for h in hits:
            if not any(s["id"] == h["id"] for s in sources):
                sources.append({"id": h["id"], "kind": h["kind"], "name": h["name"], "how": "listed", "score": h["score"]})
        return prompt, meta, notes, sources

    # -- execution ------------------------------------------------------
    def _dispatch(self, spec: str, prompt: str, cwd: str, read_only: bool, attempt: int) -> Result:
        kind, _, arg = spec.partition(":")
        with otel.span(
            "router.dispatch",
            {"router.worker": kind, "router.worker_arg": arg or "", "router.read_only": read_only},
        ):
            if kind == "pi":
                nimcfg = self.cfg["nim"]
                return self.pi.run(prompt, cwd, self.pool, prefer=arg or nimcfg["default_key"],
                                   retries=nimcfg.get("retries", 1), backoff_s=nimcfg.get("backoff_s", 3), read_only=read_only)
            if kind == "goose":
                nimcfg = self.cfg["nim"]
                return self.goose.run(prompt, cwd, self.pool, prefer=arg or nimcfg["default_key"],
                                      retries=nimcfg.get("retries", 1), backoff_s=nimcfg.get("backoff_s", 3), read_only=read_only)
            if kind == "openhands":
                return self.openhands.run(prompt, cwd, read_only=read_only)
            if kind == "or":  # OpenRouter free model: second opinion with different weights, read-only by construction
                model = arg or self.cfg.get("openrouter", {}).get("default_model", "openrouter/free")
                return self.pi.run_fixed(prompt, cwd, "OPENROUTER_API_KEY", "openrouter/" + model, read_only=True)
            if kind == "browser":  # read the URLs in the request through the Ego browser (space released afterwards), then reason on NIM
                from . import browser
                nimcfg = self.cfg["nim"]
                return browser.run(prompt, uuid.uuid4().hex[:6], lambda full: self.pi.run(
                    full, cwd, self.pool, prefer=arg or nimcfg["default_key"], retries=nimcfg.get("retries", 1),
                    backoff_s=nimcfg.get("backoff_s", 3), read_only=True))
            if kind == "opencode":
                return self.opencode.run(prompt, cwd, key=arg or nimcfg_default(self), read_only=read_only)
            if kind == "agy":
                return self.agy.run(prompt, cwd)
            if kind == "jcode":
                k = arg or nimcfg_default(self)
                return self.jcode.run(prompt, cwd, key=k, token=self.pool.value(k), read_only=read_only)
            if kind in ("claude", "codex"):
                with self._expert_lock:
                    return (self.claude if kind == "claude" else self.codex).run(prompt, cwd, read_only=read_only)
            return Result(False, f"unknown worker '{spec}'", spec)

    def run(self, text: str, *, session: Optional[str] = None, project: str = "", cwd: Optional[str] = None,
            gate: Optional[str] = None, isolate: bool = True, worker: str = "", read_only: bool = False,
            use_vault: bool = True, escalate: Optional[str] = None, on_start: Optional[Callable[[str], None]] = None) -> dict:
        w, werr = resolve_worker(parse(text).worker, worker)
        if werr:
            return {"state": "failed", "error": werr}
        if w.startswith("host:"):
            from . import remote
            name, _, rworker = w[5:].partition(":")  # host:NAME[:worker]  e.g. host:oracle:nim2
            h = self.cfg.get("hosts", {}).get(name)
            if not h:
                return {"state": "failed", "error": f"unknown host '{name}'; known: {sorted(self.cfg.get('hosts', {}))}"}
            t = parse(text)
            body = (f"/{t.command} " if t.command else "") + t.prompt
            return remote.run(h, body, {"cwd": cwd, "gate_cmd": gate, "read_only": read_only, "project": project,
                                        "worker": rworker if rworker else ""})
        rid = uuid.uuid4().hex[:8]
        if on_start:
            self._on_start[rid] = on_start
        opts = {"session": session, "project": project, "cwd": cwd, "gate": gate, "isolate": isolate, "worker": worker,
                "read_only": read_only, "use_vault": use_vault, "escalate": escalate}
        with otel.span(
            "router.run",
            {"router.rid": rid, "router.text": text[:300], "router.project": project,
             "router.worker": w or "", "router.session": session or "", "router.read_only": read_only},
        ):
            return self._invoke({"rid": rid, "text": text, "opts": opts}, rid)

    def allowed(self) -> dict:
        cmds = {r["name"] for r in self.con.execute("SELECT name FROM library WHERE kind='command'")}
        workers = {f"nim{i + 1}" for i in range(len(self.pool.names))} | ({"or"} if os.environ.get("OPENROUTER_API_KEY") else set())
        import shutil
        if self.cfg.get("decide", {}).get("allow_experts", False):  # experts cost your own subscription: opt-in only
            workers |= {w for w in ("claude", "codex") if shutil.which(self.cfg.get("workers", {}).get(w, {}).get("cmd", w))}
        if shutil.which(self.cfg.get("workers", {}).get("goose", {}).get("cmd", "goose")):
            workers.add("goose")
        if shutil.which(self.cfg.get("workers", {}).get("openhands", {}).get("cmd", "openhands")):
            workers.add("openhands")
        caps = os.path.join(ROOT, "data", "capabilities.json")  # from `backbone doctor`: drop agents that failed their probe
        if os.path.exists(caps):
            bad = {a["name"] for a in json.load(open(caps)).get("agents", []) if a.get("usable") is False}
            workers -= bad
        from . import browser as _b
        if _b.available():
            workers.add("browser")
        workers |= {f"host:{h}" for h in self.cfg.get("hosts", {})}  # remote hosts run their own cheap workers
        return {"commands": cmds, "projects": set(self.projects), "workers": workers,
                "gates": set(self.cfg.get("gates", {})), "default_worker": f"nim1"}

    def ask(self, text: str, **opts) -> dict:
        """Free-text front door: the model analyzes the goal, retrieval picks persona/command/skills, the composer builds the
        engineered prompt, the tier policy picks the worker, the router runs it, a critic reviews opinion-type results.
        opts: dry=True returns the engineered prompt and the plan without running anything."""
        from . import compose, understand
        from .decide import decide, named_persona
        al = self.allowed()
        llm = lambda m: self.chat(m, max_tokens=500)
        analysis = understand.analyze(llm, text)
        hits = self.retrieve(text, k=6)
        al["personas"] = {r["name"]: r["kind"] for r in self.con.execute("SELECT name, kind FROM library WHERE kind IN ('agent','subagent','skill')")}
        plan = decide(llm, text, al, hits)
        named = named_persona(text, al["personas"])  # owner named it: beats the model's guess
        if named:
            plan["persona"], plan["command"], plan["decided_by"] = named, "", "named"
        t = parse(text)
        row = lambda kind, name: library.get(self.con, kind, name) if name else None
        persona = row(al["personas"].get(plan["persona"], "agent"), plan["persona"]) if plan["persona"] and not t.command else None
        command = row("command", plan["command"]) if plan["command"] and not t.command else None
        skills = [r for r in (row(h["kind"], h["name"]) for h in hits if h["kind"] == "skill" and h["name"] != plan["persona"]
                                                  and h["name"] not in self.cfg.get("exclude_refs", [])) if r][:1]
        prompt, sources = compose.build(text, analysis, persona, command, skills)
        worker, why = compose.pick_tier(analysis["task_class"], self.cfg.get("tiers", {}), al["workers"], al["default_worker"])
        worker = opts.get("worker") or worker
        plan.update(task_class=analysis["task_class"], tier_reason=why, worker=worker)
        if opts.get("dry"):
            return {"state": "dry", "prompt": prompt, "prompt_sources": sources, "analysis": analysis, "plan": plan}
        gate = opts.get("gate") or (self.named_gate(plan["gate"]) if plan["gate"] else None)
        res = self.run(text if t.command else prompt, project=opts.get("project") or plan["project"], worker=worker, gate=gate,
                       read_only=opts.get("read_only", plan["read_only"] or analysis["task_class"] in ("review", "research", "plan", "draft")),
                       cwd=opts.get("cwd"))
        res["plan"], res["analysis"] = plan, analysis
        res["prompt_sources"] = sources + [x for x in res.get("prompt_sources", []) if x["id"] not in {y["id"] for y in sources}]
        if plan["critic"] and res.get("output") and os.environ.get("OPENROUTER_API_KEY"):
            from . import orchat
            from .critic import critique
            res["critic"] = critique(lambda m: orchat.chat(m), text, res["output"])
        return res

    def resume(self, rid: str) -> dict:
        """Continue a checkpointed run after a crash: picks up at the node after the last completed one."""
        return self._invoke(None, rid)

    def _invoke(self, init, rid: str) -> dict:
        cfg = {"configurable": {"thread_id": rid}}
        try:
            final = self.graph.invoke(init, cfg)
            return final["out"]
        except StaleLease as e:  # this process was reaped: its writes are rejected; the reaper's ticket is the record
            self.graph.stop_beat(rid)
            return {"run": rid, "state": "fenced", "error": str(e), "ticket": "", "patch": ""}
        except Exception as e:  # unexpected: keep the worktree for `resume`, save what the worker did, leave a ticket
            patch = ""
            try:
                st = self.graph.get_state(cfg).values
                if st.get("ws_path"):
                    from .workspace import Workspace
                    d = Workspace.attach(st["proj_path"], st["ws_path"], st.get("ws_base", ""), st.get("isolated", False)).diff()
                    patch = self.runs.save_patch(rid, d) if d else ""
            except Exception:
                pass
            self.graph.stop_beat(rid)
            t = self.runs.ticket(rid, f"{type(e).__name__}: {e}", f"rerun `runs resume {rid}` (checkpointed); patch so far: {patch}")
            self.runs.set(rid, "failed", error=str(e))
            return {"run": rid, "state": "failed", "error": str(e), "ticket": t, "patch": patch}

    def fanout(self, prompts: List[str], *, project: str = "", cwd: Optional[str] = None, gate: Optional[str] = None,
               session: Optional[str] = None, workers: Optional[List[str]] = None) -> List[dict]:
        keys = self.pool.names or [self.cfg["nim"]["default_key"]]
        slots = workers or [f"pi:{keys[i % len(keys)]}" for i in range(len(prompts))]
        with ThreadPoolExecutor(max_workers=len(prompts)) as ex:
            futs = [ex.submit(self.run, p, project=project, cwd=cwd, gate=gate, session=session, worker=slots[i], use_vault=False)
                    for i, p in enumerate(prompts)]
            return [f.result() for f in futs]

    def swarm(self, goal: str, *, n=None, project: str = "", cwd: Optional[str] = None, gate: Optional[str] = None) -> dict:
        """Planner (NIM1) picks the subtask count (n=None/'auto'), capped; workers run in parallel, depth 1."""
        n = swarm_cap(n, self.cfg.get("swarm", {}).get("max_workers", 8), self.pool.rpm_limit, len(self.pool.names))
        raw = self.chat([{"role": "user", "content": (
            f"Split this goal into as many independent subtasks as it needs, at most {n}, that touch different files. Do NOT include a "
            f"summary, write-up or merge subtask: a separate step does that after the others finish. Reply with ONLY a "
            f"JSON array of strings, each a self-contained instruction.\n\nGoal: {goal}")}], max_tokens=800)
        m = re.search(r"\[.*\]", raw, re.S)
        try:
            subs = [str(s) for s in json.loads(m.group(0))][:n] if m else []
        except Exception:
            subs = []
        if not subs:
            subs = [goal]
        results = self.fanout(subs, project=project, cwd=cwd, gate=gate)
        if len(subs) < 2:
            return {"plan": subs, "results": results}
        parts = "\n\n".join(f"### Subtask {i + 1}: {s}\n{str(r.get('output', r.get('error', '')))[:6000]}"
                            for i, (s, r) in enumerate(zip(subs, results)))
        final = self.run(f"Goal: {goal}\n\nThe subtasks are finished. Their outputs are below. Use ONLY these outputs "
                         f"(do not invent facts) to complete the goal.\n\n{parts}",
                         project=project, cwd=cwd, gate=gate, use_vault=False)
        return {"plan": subs, "results": results, "final": final}

    def resume_stale(self) -> List[dict]:
        """Runs whose lease expired (process died): mark failed and write a ticket. Retrying is an explicit rerun."""
        out = []
        for r in self.runs.stale():
            if self.con.execute("SELECT 1 FROM jobs WHERE run_id=? AND state='pending'", (r["id"],)).fetchone():
                continue  # a pending job will resume it from its checkpoint
            t = self.runs.ticket(r["id"], "process died or was stopped (lease expired)", "rerun with the same prompt; compare steps first")
            self.runs.reap(r["id"], "lease expired")
            import shutil
            shutil.rmtree(os.path.join(self.work_root, r["id"]), ignore_errors=True)
            out.append({"run": r["id"], "ticket": t})
        return out
