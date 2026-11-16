"""CLI: python -m backbone <cmd>. Run under `with-env NIM_1 NIM_2 NIM_3 --` so keys reach workers."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import library
from .core import Backbone


def _j(o) -> None:
    print(json.dumps(o, indent=2, default=str))


_EVAL = {
    "librarian": ("librarian.py", "catalog report (passthrough args)"),
    "aa-replay": ("backfill_aa.py", "A/A replay (passthrough args)"),
    "enrich": ("shadow_enrich.py", "enrich shadow receipts (passthrough args)"),
}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="backbone")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one task: [/command] [#project] [@worker] prompt")
    r.add_argument("prompt", nargs="+")
    r.add_argument("--cwd"); r.add_argument("--project", default=""); r.add_argument("--session")
    r.add_argument("--gate", help="acceptance command run by the router (exit 0 = pass)")
    r.add_argument("--worker", default=""); r.add_argument("--no-isolate", action="store_true")
    r.add_argument("--read-only", action="store_true"); r.add_argument("--no-vault", action="store_true")
    r.add_argument("--escalate", default=None); r.add_argument("--force-worker", action="store_true")

    f = sub.add_parser("fanout", help="run several prompts in parallel, one NIM key each")
    f.add_argument("prompts", nargs="+"); f.add_argument("--cwd"); f.add_argument("--gate"); f.add_argument("--project", default="")

    s = sub.add_parser("swarm", help="planner splits a goal, workers run subtasks in parallel")
    s.add_argument("goal"); s.add_argument("-n", default="auto", help="worker count or auto"); s.add_argument("--cwd"); s.add_argument("--gate"); s.add_argument("--project", default="")

    wf = sub.add_parser("workflow", help="run a workflow DAG: workflow <id> <prompt>")
    wf.add_argument("workflow_id")
    wf.add_argument("prompt", nargs="+")
    wf.add_argument("--cwd"); wf.add_argument("--project", default=""); wf.add_argument("--gate")
    wf.add_argument("--read-only", action="store_true"); wf.add_argument("--no-vault", action="store_true")

    lib = sub.add_parser("library"); ls = lib.add_subparsers(dest="lcmd", required=True)
    ls.add_parser("ingest"); ls.add_parser("counts"); ls.add_parser("embed")
    q = ls.add_parser("search"); q.add_argument("query"); q.add_argument("--kind"); q.add_argument("-k", type=int, default=5)

    cat = sub.add_parser("catalog", help="catalog operations: catalog ingest")
    ccat = cat.add_subparsers(dest="ccmd")
    ccat.add_parser("ingest", help="ingest ECC personas + agency agents into catalog skills")

    rag = sub.add_parser("rag", help="RAG operations: rag index-vault / search-vault")
    rrag = rag.add_subparsers(dest="rcmd2", required=True)
    rag_idx = rrag.add_parser("index-vault", help="index vault pages into RAG library")
    rag_idx.add_argument("--dir", default="~/memory-vault/pages"); rag_idx.add_argument("--limit", type=int, default=5000)
    rag_s = rrag.add_parser("search-vault", help="search vault pages in RAG")
    rag_s.add_argument("query"); rag_s.add_argument("-k", type=int, default=5)

    rn = sub.add_parser("runs"); rs = rn.add_subparsers(dest="rcmd", required=True)
    rs.add_parser("list"); rsm = rs.add_parser("resume"); rsm.add_argument("id"); sh = rs.add_parser("show"); sh.add_argument("id"); rs.add_parser("recover")
    sm = sub.add_parser("submit", help="queue a task for the daemon (runs even if you disconnect)")
    sm.add_argument("prompt", nargs="+"); sm.add_argument("--cwd"); sm.add_argument("--project", default="")
    sm.add_argument("--gate"); sm.add_argument("--worker", default="")
    jb = sub.add_parser("jobs"); jb.add_argument("jcmd", choices=["list"])
    dm = sub.add_parser("daemon"); dm.add_argument("--poll", type=float, default=5.0); dm.add_argument("--parallel", type=int, default=2)
    wt = sub.add_parser("watch", help="check repos for new commits; pull + re-ingest + embed changed ones")
    wt.add_argument("repos", nargs="*"); wt.add_argument("--dir", default="~/Developer/refs")
    sv = sub.add_parser("serve", help="loopback HTTP API for adapters (Telegram, Hermes, UI); needs BACKBONE_TOKEN")
    sv.add_argument("--port", type=int, default=8799)
    ak = sub.add_parser("ask", help="free text: NIM1 decides command/project/worker/gate (validated), router runs, critic reviews")
    ak.add_argument("text", nargs="+"); ak.add_argument("--cwd"); ak.add_argument("--dry", action="store_true", help="print the engineered prompt + plan, run nothing")
    tp = sub.add_parser("telegram-pair", help="pair a dedicated Telegram bot: send /start to it, the router captures your chat id (token from env ROUTER_BOT_TOKEN)")
    tp.add_argument("--wait", type=int, default=120)
    nd = sub.add_parser("node", help="connect OUTBOUND to a hub, claim jobs addressed to @node:NAME, run them here")
    nd.add_argument("--hub", required=True, help="hub serve URL, e.g. http://127.0.0.1:8799 (through an ssh -L tunnel)"); nd.add_argument("--name", required=True)
    dr = sub.add_parser("doctor", help="probe every detected agent with one tiny headless call (uses your logins briefly)")
    dr.add_argument("--only", nargs="*")
    sub.add_parser("discover", help="detect agents, keys, ssh hosts, projects on this machine")
    sub.add_parser("init", help="write ~/.agent-router/backbone.yaml from what discover found")
    sub.add_parser("keys")
    sub.add_parser("mcp")
    for n, (_f, h) in _EVAL.items():
        sub.add_parser(n, help=h)
    rr = sub.add_parser("router-report", help="hook A/B report: treat vs holdout follow rate")
    rr.add_argument("--json", action="store_true"); rr.add_argument("--receipts"); rr.add_argument("--outcomes")
    dg = sub.add_parser("digest", help="watcher snapshot: enforcement, Nina router calls, runs, bandit (logs only, no prompts)")
    dg.add_argument("--hours", type=float, default=24.0); dg.add_argument("--write", action="store_true")
    pl = sub.add_parser("plan", help="deterministic plan for a prompt: class, worker pick (bandit), compiled command; --table shows learned cells")
    pl.add_argument("text", nargs="*"); pl.add_argument("--table", action="store_true")
    cp = sub.add_parser("compile", help="prompt -> compact card (entities kept verbatim)")
    cp.add_argument("text"); cp.add_argument("--no-llm", action="store_true")
    a, rest = ap.parse_known_args(argv)
    if a.cmd in _EVAL:
        import importlib.util as _u
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _os_chdir = os.chdir
        _os_chdir(root)
        sp = _u.spec_from_file_location(a.cmd, os.path.join(root, "eval", _EVAL[a.cmd][0]))
        m = _u.module_from_spec(sp); sp.loader.exec_module(m)
        raise SystemExit(m.main(rest) or 0)
    if rest:
        ap.error("unrecognized arguments: " + " ".join(rest))
    if a.cmd == "router-report":
        from . import hook_log
        hl = ["report"] + (["--json"] if a.json else [])
        for k in ("receipts", "outcomes"):
            if getattr(a, k):
                hl += ["--" + k, getattr(a, k)]
        raise SystemExit(hook_log.main(hl))
    if a.cmd == "digest":
        from . import digest as _d
        raise SystemExit(_d.main(["--hours", str(a.hours)] + (["--write"] if a.write else [])))
    if a.cmd == "plan":
        from . import plan as _p
        from .bandit import Bandit
        b = Bandit(_p.bandit_path())
        print(json.dumps(b.table() if a.table else _p.plan(" ".join(a.text), bandit=b), indent=1))
        return
    if a.cmd == "compile":
        from . import compile as _c
        raise SystemExit(_c.main([a.text] + (["--no-llm"] if a.no_llm else [])))
    if a.cmd == "mcp":
        from .mcp_server import serve
        serve()
        return
    if a.cmd in ("discover", "init"):
        from .discover import discover, init_config
        from .core import load_config
        import yaml
        caps = discover()
        if a.cmd == "discover":
            _j(caps)
        else:
            cfg = init_config(caps, load_config(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "backbone.yaml")))
            home = os.path.expanduser("~/.agent-router")
            os.makedirs(home, exist_ok=True)
            for k in ("db", "tickets_dir", "runs_dir", "work_dir", "graph_db"):
                cfg[k] = f"~/.agent-router/data/{os.path.basename(str(cfg.get(k, k)).rstrip('/'))}"
            cfg["projects_file"] = os.path.join(home, "projects.yaml")
            yaml.safe_dump(cfg, open(os.path.join(home, "backbone.yaml"), "w"), sort_keys=False)
            yaml.safe_dump({"projects": [{"id": os.path.basename(p), "path": p, "name": os.path.basename(p)} for p in caps["projects"]]},
                           open(cfg["projects_file"], "w"), sort_keys=False)
            print("wrote", home + "/backbone.yaml;", len(caps["projects"]), "projects; ssh hosts you can add under `hosts:`:", caps["ssh_hosts"])
        return
    if a.cmd == "doctor":
        from .discover import discover
        from .doctor import run as doctor_run
        import tempfile
        out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "doctor.json")
        res = doctor_run(discover()["agents"], tempfile.mkdtemp(prefix="doctor-"), out, a.only)
        from . import health
        health.save(os.path.join(os.path.dirname(out), "doctor.json"), res)
        _j(res)
        return
    bb = Backbone()
    if a.cmd == "telegram-pair":
        import os as _os
        from . import pairing
        from .notify import _cred
        tok = _os.environ.get("ROUTER_BOT_TOKEN", "") or _cred("TELEGRAM_BOT_TOKEN")
        if not tok:
            raise SystemExit("no bot token: set it in the router secrets file or export ROUTER_BOT_TOKEN; it is never printed")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        print(json.dumps(pairing.pair(tok, os.path.join(root, ".env.local"), a.wait)))
        return
    if a.cmd == "node":
        from . import node
        node.loop(bb, a.hub, a.name)
        return
    if a.cmd == "ask":
        _j(bb.ask(" ".join(a.text), cwd=a.cwd, dry=a.dry))
    elif a.cmd == "run":
        import os as _o
        from . import health
        hp = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "data", "doctor.json")
        worker, esc = a.worker, a.escalate
        if not a.force_worker:
            want = worker or next((t[1:] for t in a.prompt if t.startswith("@")), "")
            if want in ("claude", "codex") and not health.usable(hp, want):
                alt = health.pick([w for w in ("claude", "codex") if w in bb.cfg.get("workers", {})], lambda w: health.usable(hp, w))
                if not alt:
                    print(f"no usable worker per doctor ({want} down); --force-worker to bypass", file=sys.stderr)
                    raise SystemExit(3)
                print(f"worker {want} unusable per doctor; using {alt}", file=sys.stderr)
                worker = alt
            ex = bb.cfg.get("escalation", {}).get("expert", "") if esc is None else esc
            if ex and not health.usable(hp, ex):
                print(f"escalation expert {ex} unusable per doctor; escalation off", file=sys.stderr)
                esc = ""
        _j(bb.run(" ".join(a.prompt), session=a.session, project=a.project, cwd=a.cwd,
                  gate=health.rewrite_gate(a.gate, a.cwd or _o.getcwd()) if a.gate else a.gate,
                  isolate=not a.no_isolate, worker=worker, read_only=a.read_only, use_vault=not a.no_vault,
                  escalate=esc))
    elif a.cmd == "fanout":
        _j(bb.fanout(a.prompts, project=a.project, cwd=a.cwd, gate=a.gate))
    elif a.cmd == "swarm":
        _j(bb.swarm(a.goal, n=None if a.n == "auto" else int(a.n), project=a.project, cwd=a.cwd, gate=a.gate))
    elif a.cmd == "workflow":
        from . import workflow as _wf
        res = _wf.run_workflow(bb, a.workflow_id, " ".join(a.prompt), a.cwd or os.getcwd(),
                               read_only=a.read_only)
        _j({"workflow_id": res.workflow_id, "ok": res.ok, "synthesis": res.synthesis,
            "steps": {sid: {"ok": sr.ok, "worker": sr.worker, "output": sr.output,
                            "gate_passed": sr.gate_passed, "error": sr.error}
                    for sid, sr in res.step_results.items()}})
    elif a.cmd == "library":
        if a.lcmd == "ingest":
            _j(bb.ingest())
        elif a.lcmd == "embed":
            print(bb.rag.embed_missing(), "embedded")
        elif a.lcmd == "counts":
            _j(library.counts(bb.con))
        else:
            for h in bb.rag.search(a.query, a.kind, a.k):
                print(f"{h['kind']:8} {h['name']:30} {h['via']:5} {h['description'][:70]}")
    elif a.cmd == "catalog":
        if a.ccmd == "ingest":
            from .catalog_ingest import ingest_all
            ecc = os.path.expanduser("~/Developer/ecc-reference/agents")
            agency = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
            skills = ingest_all(ecc, agency)
            _j({"ingested": len(skills), "skills": skills})
        else:
            ap.error("catalog requires: ingest")
    elif a.cmd == "rag":
        if a.rcmd2 == "index-vault":
            from . import rag as _rag_mod
            count = bb.rag.index_vault(a.dir, limit=a.limit)
            print(f"indexed {count} vault pages")
        elif a.rcmd2 == "search-vault":
            for h in bb.rag.search_vault(a.query, k=a.k):
                print(f"{h['kind']:8} {h['name']:30} {h['via']:5} {h['description'][:70]}")
    elif a.cmd == "runs":
        if a.rcmd == "list":
            _j(bb.runs.list())
        elif a.rcmd == "resume":
            _j(bb.resume(a.id))
        elif a.rcmd == "show":
            _j({"run": bb.runs.get(a.id), "steps": bb.runs.steps(a.id)})
        else:
            _j(bb.resume_stale())
    elif a.cmd in ("submit", "jobs", "daemon"):
        from .jobs import Jobs
        jobs = Jobs(bb)
        if a.cmd == "submit":
            opts = {k: v for k, v in dict(cwd=a.cwd, project=a.project, gate=a.gate, worker=a.worker).items() if v}
            print(jobs.submit(" ".join(a.prompt), **opts))
        elif a.cmd == "jobs":
            _j(jobs.list())
        else:
            jobs.daemon(poll_s=a.poll, max_parallel=a.parallel)
    elif a.cmd == "watch":
        _j(bb.watch_once(a.repos or None, a.dir) or {"unchanged": a.repos or bb.cfg.get("watch", {}).get("repos", [])})
    elif a.cmd == "serve":
        from .serve import serve
        serve(bb, port=a.port)
    elif a.cmd == "keys":
        _j(bb.pool.status())


if __name__ == "__main__":
    main(sys.argv[1:])
