"""CLI: python -m backbone <cmd>. Run under `with-env NIM_1 NIM_2 NIM_3 --` so keys reach workers."""
from __future__ import annotations

import argparse
import json
import sys

from . import library
from .core import Backbone


def _j(o) -> None:
    print(json.dumps(o, indent=2, default=str))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="backbone")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one task: [/command] [#project] [@worker] prompt")
    r.add_argument("prompt", nargs="+")
    r.add_argument("--cwd"); r.add_argument("--project", default=""); r.add_argument("--session")
    r.add_argument("--gate", help="acceptance command run by the router (exit 0 = pass)")
    r.add_argument("--worker", default=""); r.add_argument("--no-isolate", action="store_true")
    r.add_argument("--read-only", action="store_true"); r.add_argument("--no-vault", action="store_true")
    r.add_argument("--escalate", default=None)

    f = sub.add_parser("fanout", help="run several prompts in parallel, one NIM key each")
    f.add_argument("prompts", nargs="+"); f.add_argument("--cwd"); f.add_argument("--gate"); f.add_argument("--project", default="")

    s = sub.add_parser("swarm", help="planner splits a goal, workers run subtasks in parallel")
    s.add_argument("goal"); s.add_argument("-n", type=int, default=3); s.add_argument("--cwd"); s.add_argument("--gate"); s.add_argument("--project", default="")

    lib = sub.add_parser("library"); ls = lib.add_subparsers(dest="lcmd", required=True)
    ls.add_parser("ingest"); ls.add_parser("counts"); ls.add_parser("embed")
    q = ls.add_parser("search"); q.add_argument("query"); q.add_argument("--kind"); q.add_argument("-k", type=int, default=5)

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
    dr = sub.add_parser("doctor", help="probe every detected agent with one tiny headless call (uses your logins briefly)")
    dr.add_argument("--only", nargs="*")
    sub.add_parser("discover", help="detect agents, keys, ssh hosts, projects on this machine")
    sub.add_parser("init", help="write ~/.agent-router/backbone.yaml from what discover found")
    sub.add_parser("keys")
    sub.add_parser("mcp")
    a = ap.parse_args(argv)

    if a.cmd == "mcp":
        from .mcp_server import serve
        serve()
        return
    if a.cmd in ("discover", "init"):
        from .discover import discover, init_config
        from .core import load_config
        import yaml, os as _os
        caps = discover()
        if a.cmd == "discover":
            _j(caps)
        else:
            cfg = init_config(caps, load_config(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "config", "backbone.yaml")))
            home = _os.path.expanduser("~/.agent-router")
            _os.makedirs(home, exist_ok=True)
            for k in ("db", "tickets_dir", "runs_dir", "work_dir", "graph_db"):
                cfg[k] = f"~/.agent-router/data/{_os.path.basename(str(cfg.get(k, k)).rstrip('/'))}"
            cfg["projects_file"] = _os.path.join(home, "projects.yaml")
            yaml.safe_dump(cfg, open(_os.path.join(home, "backbone.yaml"), "w"), sort_keys=False)
            yaml.safe_dump({"projects": [{"id": _os.path.basename(p), "path": p, "name": _os.path.basename(p)} for p in caps["projects"]]},
                           open(cfg["projects_file"], "w"), sort_keys=False)
            print("wrote", home + "/backbone.yaml;", len(caps["projects"]), "projects; ssh hosts you can add under `hosts:`:", caps["ssh_hosts"])
        return
    if a.cmd == "doctor":
        from .discover import discover
        from .doctor import run as doctor_run
        import tempfile
        out = _os_path = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), "data", "capabilities.json")
        _j(doctor_run(discover()["agents"], tempfile.mkdtemp(prefix="doctor-"), out, a.only))
        return
    bb = Backbone()
    if a.cmd == "ask":
        _j(bb.ask(" ".join(a.text), cwd=a.cwd, dry=a.dry))
    elif a.cmd == "run":
        _j(bb.run(" ".join(a.prompt), session=a.session, project=a.project, cwd=a.cwd, gate=a.gate,
                  isolate=not a.no_isolate, worker=a.worker, read_only=a.read_only, use_vault=not a.no_vault,
                  escalate=a.escalate))
    elif a.cmd == "fanout":
        _j(bb.fanout(a.prompts, project=a.project, cwd=a.cwd, gate=a.gate))
    elif a.cmd == "swarm":
        _j(bb.swarm(a.goal, n=a.n, project=a.project, cwd=a.cwd, gate=a.gate))
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
