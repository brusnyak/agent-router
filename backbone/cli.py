"""CLI: python -m backbone <cmd>. Run under `with-env NIM_1 NIM_2 NIM_3 --` so keys reach workers."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import library


def vault_dir(*parts):
    from .paths import vault_dir as _v
    return _v(*parts)

def Backbone(*args, **kwargs):
    """Lazy factory: lightweight commands need no optional worker dependencies."""
    from .core import Backbone as implementation
    return implementation(*args, **kwargs)


def _j(o) -> None:
    from .redact import redact
    print(redact(json.dumps(o, indent=2, default=str)))


_EVAL = {
    "librarian": ("librarian.py", "catalog report (passthrough args)"),
    "aa-replay": ("backfill_aa.py", "A/A replay (passthrough args)"),
    "enrich": ("shadow_enrich.py", "enrich shadow receipts (passthrough args)"),
}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="backbone")
    sub = ap.add_subparsers(dest="cmd", required=True)

    retrieval = sub.add_parser("retrieval", help="pluggable memory retrieval")
    retrieval.add_argument("retrieval_args", nargs=argparse.REMAINDER)

    r = sub.add_parser("run", help="run one task: [/command] [#project] [@worker] prompt")
    r.add_argument("prompt", nargs="+")
    r.add_argument("--cwd"); r.add_argument("--project", default=""); r.add_argument("--session")
    r.add_argument("--gate", help="acceptance command run by the router (exit 0 = pass)")
    r.add_argument("--worker", default=""); r.add_argument("--no-isolate", action="store_true")
    r.add_argument("--read-only", action="store_true"); r.add_argument("--no-vault", action="store_true")
    r.add_argument("--escalate", default=None); r.add_argument("--force-worker", action="store_true")
    d = sub.add_parser("delegate", help="delegate a goal to bounded subagents: split -> fanout -> integrate -> gate")
    d.add_argument("goal"); d.add_argument("--cwd"); d.add_argument("--project", default=""); d.add_argument("--gate")
    d.add_argument("--worker", default=""); d.add_argument("--no-isolate", action="store_true")
    d.add_argument("--read-only", action="store_true"); d.add_argument("--max-subagents", type=int, default=3)
    im = sub.add_parser("improve", help="propose skill/command maintenance from outcomes + receipts")
    im.add_argument("--receipts", default=os.path.expanduser("~/.agent-router/hook-shadow.jsonl"))
    im.add_argument("--db", default=os.path.expanduser("~/.agent-router/data/backbone.db"))
    im.add_argument("--out", default=os.path.expanduser("~/.agent-router/improve-report.md"))
    im.add_argument("--top", type=int, default=40)

    f = sub.add_parser("fanout", help="run several prompts in parallel, one NIM key each")
    f.add_argument("prompts", nargs="+"); f.add_argument("--cwd"); f.add_argument("--gate"); f.add_argument("--project", default="")
    dp = sub.add_parser("dispatch", help="lease-guarded, wave-scheduled dispatch of packet files")
    dp.add_argument("packets", nargs="+", help="packet .md files")
    dp.add_argument("--cwd"); dp.add_argument("--project", default=""); dp.add_argument("--parallel", type=int, default=None)
    dp.add_argument("--workers", default="", help="comma separated worker specs, e.g. omp,pi,kilo")
    dp.add_argument("--dry-run", action="store_true", help="print wave plan only, no model calls")

    s = sub.add_parser("swarm", help="planner splits a goal, workers run subtasks in parallel")
    s.add_argument("goal"); s.add_argument("-n", default="auto", help="worker count or auto"); s.add_argument("--cwd"); s.add_argument("--gate"); s.add_argument("--project", default="")

    wf = sub.add_parser("workflow", help="run a workflow DAG: workflow <id> <prompt>")
    wf.add_argument("workflow_id")
    wf.add_argument("prompt", nargs="+")
    wf.add_argument("--cwd"); wf.add_argument("--project", default=""); wf.add_argument("--gate")
    wf.add_argument("--read-only", action="store_true"); wf.add_argument("--no-vault", action="store_true")

    lib = sub.add_parser("library"); ls = lib.add_subparsers(dest="lcmd", required=True)
    ls.add_parser("ingest"); ls.add_parser("counts"); ls.add_parser("embed")
    so = ls.add_parser("sources", help="scan the machine for skill/agent/command sources; --apply registers + ingests + re-exports the hook index")
    so.add_argument("--apply", action="store_true")
    xi = ls.add_parser("export-index", help="export compact hook-consumable library index to JSONL")
    xi.add_argument("--out", default="~/.agent-router/library-index.jsonl")
    xi.add_argument("--kinds", nargs="*", default=["skill", "agent", "subagent", "command"])
    xi.add_argument("--limit-per-kind", type=int, default=None)
    q = ls.add_parser("search"); q.add_argument("query"); q.add_argument("--kind"); q.add_argument("-k", type=int, default=5)

    cat = sub.add_parser("catalog", help="catalog operations: catalog ingest, catalog models")
    ccat = cat.add_subparsers(dest="ccmd")
    ccat.add_parser("ingest", help="ingest ECC personas + agency agents into catalog skills")
    models = ccat.add_parser("models", help="snapshot and probe free models once per UTC day")
    models.add_argument("--out", default="~/.agent-router/model_catalog.json")
    models.add_argument("--force", action="store_true", help="repeat today's probes")

    rag = sub.add_parser("rag", help="RAG operations: rag index-vault / search-vault")
    rrag = rag.add_subparsers(dest="rcmd2", required=True)
    rag_idx = rrag.add_parser("index-vault", help="index vault pages into RAG library")
    rag_idx.add_argument("--dir", default=vault_dir("pages")); rag_idx.add_argument("--limit", type=int, default=5000)
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
    apv = sub.add_parser("approvals", help="approval deck: add a card, list waiting cards, decide, ask status (swipe UI at /approvals on `backbone serve`)")
    apv.add_argument("op", choices=["add", "list", "decide", "status"]); apv.add_argument("--id", default="")
    apv.add_argument("--kind", default="other"); apv.add_argument("--title", default=""); apv.add_argument("--body", default="")
    apv.add_argument("--link", default=""); apv.add_argument("--batch", default=""); apv.add_argument("--decision", default=""); apv.add_argument("--comment", default="")
    kp = sub.add_parser("proxy", help="loopback key proxy: agents use base_url http://127.0.0.1:8790/v1 + any dummy key; real keys stay in the router")
    kp.add_argument("--port", type=int, default=0)
    sub.add_parser("discover", help="detect agents, keys, ssh hosts, projects on this machine")
    sub.add_parser("init", help="write ~/.agent-router/backbone.yaml from what discover found")
    sub.add_parser("keys")
    tk = sub.add_parser("tickets", help="submit eligible vault tickets from pages/jobs/ to the existing SQLite queue")
    tk.add_argument("--dir", default=vault_dir("pages", "jobs"), help="local vault jobs directory")
    sub.add_parser("mcp")
    for n, (_f, h) in _EVAL.items():
        sub.add_parser(n, help=h)
    rr = sub.add_parser("router-report", help="hook A/B report: treat vs holdout follow rate")
    rr.add_argument("--json", action="store_true"); rr.add_argument("--receipts"); rr.add_argument("--outcomes")

    dg = sub.add_parser("digest", help="watcher snapshot: enforcement, Nina router calls, runs, bandit (logs only, no prompts)")
    dg.add_argument("--hours", type=float, default=24.0); dg.add_argument("--write", action="store_true")
    st = sub.add_parser("stop", help="stop everything: guard pause, halt hub/daemon/node, sync to VM")
    st.add_argument("--sync", action="store_true", help="also rsync to Oracle VM via scripts/sync_vm.sh --restart")
    st.add_argument("--no-sync", action="store_true", help="do not sync to VM; stop local only")
    pl = sub.add_parser("plan", help="deterministic plan for a prompt: class, worker pick (bandit), compiled command; --table shows learned cells")
    nt = sub.add_parser("night-tick", help="run one bounded night-mode tick (PAUSE honored, read-only, gate-checked)")
    nt.add_argument("prompt", nargs="*", default="")
    nt.add_argument("--cfg", help="path to night config yaml")
    nt.add_argument("--tasks", help="path to bounded tasks.yaml queue")
    nt.add_argument("--dry-run", action="store_true", help="simulate window and one task; isolated state, no network")
    nt.add_argument("--loop", action="store_true", help="loop ticks until PAUSE or out of window")
    pt = sub.add_parser("proactive-tick", help="enqueue one eligible step from the approved persistent goal manifest")
    pt.add_argument("--manifest", default=vault_dir("pages", "plans", "proactive-goals.json"))
    pc = sub.add_parser("proactive-cycle", help="run one bounded text-only unattended goal cycle")
    pc.add_argument("--manifest", default=vault_dir("pages", "plans", "proactive-goals.json"))
    sub.add_parser("proactive-status", help="persistent proactive goal state")
    it = sub.add_parser("idle-tick", help="run one idle-tick: submit the next backlog item if idle")
    it.add_argument("--idle-minutes", type=int, default=None)

    pl.add_argument("text", nargs="*"); pl.add_argument("--table", action="store_true")
    cp = sub.add_parser("compile", help="prompt -> compact card (entities kept verbatim)")
    cp.add_argument("text"); cp.add_argument("--no-llm", action="store_true")
    mon = sub.add_parser("monitor", help="collect local or SSH host resource snapshots")
    mon.add_argument("--host", nargs="+", action="extend", default=[])
    mon.add_argument("--json", action="store_true"); mon.add_argument("--write", action="store_true")
    sub.add_parser("factory-status", add_help=False, help="read-only business factory status JSON")
    for name in ("contract", "diagnose", "recover", "status", "harness", "install", "guard"):
        sub.add_parser(name, add_help=False)
    a, rest = ap.parse_known_args(argv)
    if a.cmd == "factory-status":
        from .factory_status import main as entry
        raise SystemExit(entry(rest))
    if a.cmd in ("contract", "diagnose", "recover", "status", "harness", "install", "guard"):
        if a.cmd == "guard":
            from . import guard
            raise SystemExit(guard.main(rest))
        if a.cmd == "install":
            from . import scan
            raise SystemExit(scan.main(rest))
        if a.cmd == "harness":
            from . import harness
            raise SystemExit(harness.main(rest))
        if a.cmd == "contract":
            from .contract import main as entry
            raise SystemExit(entry(rest))
        if a.cmd == "status":
            from .status import main as entry
            raise SystemExit(entry(rest))
        from .diagnose import main as entry
        raise SystemExit(entry([a.cmd] + rest))
    if a.cmd == "retrieval":
        from .retrieval import main as retrieval_main
        raise SystemExit(retrieval_main(a.retrieval_args))
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
    if a.cmd == "monitor":
        from . import monitor
        from .core import load_config
        import re
        import socket
        limits = load_config().get("monitor", {})
        if a.host:
            snaps = [monitor.remote(host) for host in a.host]
        else:
            try:
                snaps = [monitor.collect()]
            except (OSError, ValueError, RuntimeError) as exc:
                snaps = [{"host": socket.gethostname(), "ts": monitor._ts(), "error": str(exc)}]
            except monitor.subprocess.SubprocessError as exc:
                snaps = [{"host": socket.gethostname(), "ts": monitor._ts(), "error": str(exc)}]
        alerted = False
        for snap in snaps:
            alerts = monitor.check(snap, limits)
            alerted = alerted or bool(alerts)
            if a.write:
                directory = os.path.expanduser("~/.agent-router/monitor")
                os.makedirs(directory, exist_ok=True)
                name = re.sub(r"[^A-Za-z0-9_.-]", "_", snap["host"]).lstrip(".") or "host"
                with open(os.path.join(directory, name + ".json"), "w") as stream:
                    json.dump(snap, stream, indent=2)
            if not a.json:
                print(f"{snap['host']}: " + ("; ".join(alerts) if alerts else "OK"))
                if "error" not in snap:
                    print(f"  load {snap['load1']:.2f}/{snap['cpus']} CPUs; "
                          f"available {snap['mem_avail_mb']:.0f} MiB; "
                          f"swap {snap['swap_used_mb']:.0f} MiB; disk {snap['disk_root_pct']:.1f}%")
        if a.json:
            _j(snaps[0] if len(snaps) == 1 else snaps)
        raise SystemExit(2 if alerted else 0)
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
    if a.cmd == "night-tick":
        from . import night as _n
        prompt = " ".join(a.prompt) if isinstance(a.prompt, list) else str(a.prompt or "")
        raise SystemExit(_n.run_tick(cfg_path=a.cfg, prompt=prompt, tasks_path=a.tasks, dry_run=a.dry_run))

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
            home = os.path.expanduser("~/.agent-router")
            out_path = os.path.join(home, "backbone.yaml")
            if os.path.exists(out_path):
                print(f"refusing to overwrite existing config: {out_path}; edit it by hand or remove it first")
                raise SystemExit(1)
            cfg = init_config(caps, load_config(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "backbone.yaml")))
            os.makedirs(home, exist_ok=True)
            for k in ("db", "tickets_dir", "runs_dir", "work_dir", "graph_db"):
                cfg[k] = f"~/.agent-router/data/{os.path.basename(str(cfg.get(k, k)).rstrip('/'))}"
            cfg["projects_file"] = os.path.join(home, "projects.yaml")
            projects_path = os.path.join(home, "projects.yaml")
            with open(out_path, "w") as fh:
                yaml.safe_dump(cfg, fh, sort_keys=False)
            with open(projects_path, "w") as fh:
                yaml.safe_dump({"projects": [{"id": os.path.basename(p), "path": p, "name": os.path.basename(p)} for p in caps["projects"]]},
                               fh, sort_keys=False)
            print("wrote", out_path + ";", len(caps["projects"]), "projects; ssh hosts you can add under `hosts:`:", caps["ssh_hosts"])
        return
    if a.cmd == "approvals":
        from . import approvals
        if a.op == "add":
            print(approvals.add(a.kind, a.title, a.body, a.link, None, a.batch, a.id))
        elif a.op == "list":
            _j({"counts": approvals.counts(), "cards": [{k: c[k] for k in ("id", "kind", "title", "decision")} for c in approvals.pending()]})
        elif a.op == "decide":
            print(approvals.decide(a.id, a.decision, a.comment))
        else:
            _j(approvals.status(a.id))
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
    if a.cmd == "proxy":
        from . import keyproxy
        keyproxy.serve(bb.cfg["nim"], bb.cfg["nim"]["model"], a.port or keyproxy.PORT)
        return
    if a.cmd in ("proactive-tick", "proactive-status", "proactive-cycle"):
        from . import proactive
        _j(proactive.cycle(bb, os.path.expanduser(a.manifest)) if a.cmd == "proactive-cycle" else
           proactive.tick(bb, os.path.expanduser(a.manifest)) if a.cmd == "proactive-tick" else proactive.status(bb))
        return
    if a.cmd == "idle-tick":
        from . import idle_tick as _idle
        from .core import load_config
        cfg = load_config()
        if a.idle_minutes is not None:
            cfg["idle_minutes"] = a.idle_minutes
        _j(_idle.tick(cfg))
        return
    if a.cmd == "tickets":
        from .ticket import submit_tickets
        res = submit_tickets(os.path.expanduser(a.dir), bb)
        _j(res)
        return
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
    elif a.cmd == "dispatch":
        workers = [w for w in a.workers.split(",") if w] or None
        out = bb.dispatch(a.packets, cwd=a.cwd, project=a.project, max_parallel=a.parallel,
                          workers=workers, dry_run=a.dry_run)
        if a.dry_run:
            for w in out:
                print(f"wave {w['wave']}: {', '.join(w['packets'])}")
        else:
            for r in out:
                gate = "pass" if r["gate_passed"] else "fail"
                print(f"{r['name']} | {r['worker']}/{r['key_slot']} | {r['state']} | {gate} | {r['seconds']:.2f}")
    elif a.cmd == "fanout":
        _j(bb.fanout(a.prompts, project=a.project, cwd=a.cwd, gate=a.gate))
    elif a.cmd == "swarm":
        _j(bb.swarm(a.goal, n=None if a.n == "auto" else int(a.n), project=a.project, cwd=a.cwd, gate=a.gate))
    elif a.cmd == "delegate":
        _j(bb.delegate(a.goal, project=a.project, cwd=a.cwd, gate=a.gate,
                       worker=a.worker, max_subagents=a.max_subagents,
                       read_only=a.read_only, isolate=not a.no_isolate))
    elif a.cmd == "improve":
        from . import improve as _improve
        import sqlite3
        con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        from .db import DB
        props = _improve.improve(DB(con), _improve._read_jsonl(a.receipts), top_n=a.top)
        _j({"proposals": props, "count": len(props),
            "report_path": a.out, "format": _improve.format_report(props)})
        return
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
        elif a.lcmd == "sources":
            from . import sources as _src
            cfg_src = list(bb.cfg.get("library", {}).get("sources", [])) + _src.load_registry()
            rep = _src.coverage(_src.discover(), cfg_src)
            import re as _re
            known = {_re.sub(r"[^a-z0-9]+", "-", (r[0] or "").lower()).strip("-") for r in bb.con.execute("SELECT name FROM library")} | {(r[0] or "").lower() for r in bb.con.execute("SELECT name FROM library")}
            new = _src.only_unique([r for r in rep if not r["covered"]], known)
            _j({"found": len(rep), "already_covered": len(rep) - len(new), "new": new})
            if a.apply and new:
                print("registry:", _src.save_registry(new))
                _j(bb.ingest())
                from .library import export_index
                print("index rows:", export_index(bb.con, os.path.expanduser("~/.agent-router/library-index.jsonl")))
        elif a.lcmd == "embed":
            print(bb.rag.embed_missing(), "embedded")
        elif a.lcmd == "counts":
            _j(library.counts(bb.con))
        elif a.lcmd == "export-index":
            from .library import export_index
            n = export_index(bb.con, os.path.expanduser(a.out), kinds=a.kinds,
                             limit_per_kind=a.limit_per_kind)
            print(f"exported {n} rows to {a.out}")
        else:
            for h in bb.rag.search(a.query, a.kind, a.k):
                print(f"{h['kind']:8} {h['name']:30} {h['via']:5} {h['description'][:70]}")
    elif a.cmd == "catalog":
        if a.ccmd == "models":
            from .model_catalog import snapshot
            _j(snapshot(a.out, force=a.force))
        elif a.ccmd == "ingest":
            from .catalog_ingest import ingest_all
            ecc = os.path.expanduser("~/Developer/ecc-reference/agents")
            agency = os.path.expanduser("~/.agent-skills/vendor/msitarzewski_agency-agents")
            skills = ingest_all(ecc, agency)
            _j({"ingested": len(skills), "skills": skills})
        else:
            ap.error("catalog requires: ingest or models")
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
    elif a.cmd == "stop":
        from . import stop as _stop
        raise SystemExit(_stop.main(a.sync if hasattr(a, "sync") else True, a.no_sync if hasattr(a, "no_sync") else False))


if __name__ == "__main__":
    main(sys.argv[1:])
