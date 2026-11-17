"""Offline fixtures for backbone.status: no network, no DB writes."""
import json
import os
import sqlite3
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backbone import status


def _make_db(path, now, runs=(), jobs=(), extra_tables=False):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE runs(id TEXT PRIMARY KEY, state TEXT NOT NULL, worker TEXT, "
        "command TEXT, prompt TEXT, created REAL, updated REAL, meta TEXT DEFAULT '{}')"
    )
    con.execute(
        "CREATE TABLE jobs(id TEXT PRIMARY KEY, state TEXT NOT NULL, owner TEXT, "
        "run_id TEXT, text TEXT, created REAL, updated REAL, opts TEXT DEFAULT '{}')"
    )
    if extra_tables:
        con.execute("CREATE TABLE other(x TEXT)")
    for rid, state, worker, command, prompt, created in runs:
        con.execute(
            "INSERT INTO runs(id,state,worker,command,prompt,created,updated,meta) VALUES (?,?,?,?,?,?,?,?)",
            (rid, state, worker, command, prompt, created, created, "{}"),
        )
    for jid, state, owner, run_id, text, created in jobs:
        con.execute(
            "INSERT INTO jobs(id,state,owner,run_id,text,created,updated,opts) VALUES (?,?,?,?,?,?,?,?)",
            (jid, state, owner, run_id, text, created, created, "{}"),
        )
    con.commit()
    con.close()


def _monitor_dir(tmp, snaps):
    d = os.path.join(tmp, "monitor")
    os.makedirs(d)
    for name, body, mtime in snaps:
        p = os.path.join(d, name + ".json")
        with open(p, "w") as f:
            json.dump(body, f)
        os.utime(p, (mtime, mtime))
    return d


class StatusCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(os.getcwd(), ".test_status_tmp")
        os.makedirs(self.tmp, exist_ok=True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        self.env = {"AGENT_ROUTER_HOME": self.home}
        self.old_home = os.environ.get("AGENT_ROUTER_HOME")
        os.environ["AGENT_ROUTER_HOME"] = self.home
        os.makedirs(os.path.join(self.home, "data"))

    def tearDown(self):
        if self.old_home is None:
            os.environ.pop("AGENT_ROUTER_HOME", None)
        else:
            os.environ["AGENT_ROUTER_HOME"] = self.old_home
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def db(self, name="backbone.db", **kw):
        return os.path.join(self.home, "data", name)

    def test_missing_db_unknown_not_healthy(self):
        s = status.collect(db_path=self.db("nope.db"), now=1000.0)
        self.assertFalse(s["available"])
        self.assertTrue(s["error"])
        self.assertEqual(s["counts"], {})
        self.assertIs(s["available"], False)  # unknown, not 0 healthy

    def test_malformed_schema_is_unavailable(self):
        p = self.db("bad.db")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE other(x TEXT)")
        con.commit()
        con.close()
        s = status.collect(db_path=p, now=1000.0)
        self.assertFalse(s["available"])
        self.assertTrue(s["error"])

    def test_empty_valid_db(self):
        p = self.db()
        _make_db(p, 1000.0)
        s = status.collect(db_path=p, now=1000.0)
        self.assertTrue(s["available"])
        self.assertEqual(s["error"], "")
        self.assertEqual(s["counts"], {})
        self.assertEqual(s["jobs"], {})
        self.assertEqual(s["active_tasks"], [])
        out = "\n".join(status.brief(s))
        self.assertIn("Router 0 running · 0 queued", out)
        self.assertEqual(len(status.brief(s)), 1)

    def test_running_older_than_24h_excluded_from_counts_but_stays_active(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now, runs=[("r1", "running", "pi:NIM_1", "review login", "login", now - 30 * 3600)])
        s = status.collect(db_path=p, now=now)
        self.assertTrue(s["available"])
        self.assertEqual(s["counts"].get("running", 0), 0)  # historical counts are 24h
        self.assertEqual(len(s["active_tasks"]), 1)
        t = s["active_tasks"][0]
        self.assertEqual(t["id"], "r1")
        self.assertEqual(t["state"], "running")
        self.assertEqual(t["worker"], "pi:NIM_1")
        self.assertEqual(t["title"], "review login")
        self.assertEqual(t["age"], int(30 * 3600))

    def test_progress_and_gate_only_when_present(self):
        now = 1000.0
        p = self.db()
        _make_db(
            p,
            now,
            runs=[
                ("r1", "running", "w1", "review", "review x", now - 10),
                ("r2", "running", "w2", "build", "build y", now - 20),
            ],
        )
        con = sqlite3.connect(p)
        con.execute("UPDATE runs SET meta=? WHERE id=?", (json.dumps({"progress": 0.5, "gate": "pytest"}), "r1"))
        con.commit()
        con.close()
        s = status.collect(db_path=p, now=now)
        t1, t2 = s["active_tasks"]
        self.assertEqual(t1["progress"], 0.5)
        self.assertEqual(t1["gate"], "pytest")
        self.assertNotIn("progress", t2)
        self.assertNotIn("gate", t2)

    def test_pending_and_queued_are_waiting(self):
        now = 1000.0
        p = self.db()
        _make_db(
            p,
            now,
            jobs=[
                ("j1", "pending", "", None, "wait one", now - 5),
                ("j2", "queued", "", None, "wait two", now - 6),
                ("j3", "done", "", None, "finished", now - 7),
            ],
        )
        s = status.collect(db_path=p, now=now)
        self.assertEqual(s["jobs"]["pending"], 1)
        self.assertEqual(s["jobs"]["queued"], 1)
        self.assertEqual(s["jobs"].get("done", 0), 1)
        self.assertEqual(s["counts"], {})
        states = {t["state"] for t in s["active_tasks"]}
        self.assertEqual(states, {"pending", "queued"})
        out = "\n".join(status.brief(s))
        self.assertIn("2 queued", out)

    def test_blocked_is_not_needs_user(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now, runs=[("r1", "blocked", "w1", "review", "x", now - 10)])
        s = status.collect(db_path=p, now=now)
        self.assertEqual(s["counts"].get("blocked", 0), 1)
        self.assertEqual(s["active_tasks"], [])
        out = "\n".join(status.brief(s))
        self.assertIn("Router 0 running · 0 queued", out)

    def test_linked_job_run_not_double_counted(self):
        now = 1000.0
        p = self.db()
        _make_db(
            p,
            now,
            runs=[("r1", "running", "w1", "review", "x", now - 10)],
            jobs=[("j1", "running", "", "r1", "job for r1", now - 10)],
        )
        s = status.collect(db_path=p, now=now)
        self.assertEqual(s["counts"]["running"], 1)  # run counted, linked job not
        self.assertEqual(len(s["active_tasks"]), 1)
        self.assertEqual(s["active_tasks"][0]["id"], "r1")

    def test_host_stale_and_error_labels_are_freshness_not_reachability(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now)
        mon = _monitor_dir(
            self.home,
            [
                ("mac", {"host": "mac", "load1": 2.0}, now - 1000),  # stale
                ("box", {"host": "box", "error": "ssh timeout"}, now - 10),
                ("fresh", {"host": "fresh", "load1": 0.1}, now - 10),
            ],
        )
        s = status.collect(db_path=p, now=now)
        self.assertTrue(s["available"])
        self.assertEqual(s["hosts"]["mac"]["freshness"], "stale")
        self.assertEqual(s["hosts"]["box"]["freshness"], "error")
        self.assertEqual(s["hosts"]["fresh"]["freshness"], "fresh")
        self.assertEqual(s["hosts"]["fresh"]["freshness"], "fresh")
        out = "\n".join(status.brief(s))
        self.assertIn("mac: stale", out)
        self.assertIn("box: error", out)
        self.assertNotIn("load1", out)
        self.assertNotIn("◐", out)  # no glyph history in default summary

    def test_control_characters_stripped(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now, runs=[("r1", "running", "w1", "\x1b[31mreview\x1b[0m\rlogin", "task", now - 10)])
        s = status.collect(db_path=p, now=now)
        out = "\n".join(status.brief(s))
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\r", out)
        self.assertIn("review login", out)

    def test_brief_and_details(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now, runs=[("r1", "running", "w1", "review", "x", now - 10)])
        s = status.collect(db_path=p, now=now)
        brief_out = "\n".join(status.brief(s))
        self.assertEqual(len(status.brief(s)), 2)
        det = "\n".join(status.details(s))
        self.assertIn("active tasks", det)
        self.assertIn("workers (24h history)", det)
        self.assertIn("hosts (monitor freshness)", det)

    def test_json_round_trip_keeps_keys(self):
        now = 1000.0
        p = self.db()
        _make_db(p, now)
        s = status.collect(db_path=p, now=now)
        payload = json.dumps(s)
        back = json.loads(payload)
        for key in ("ts", "available", "error", "source", "counts", "workers", "jobs", "hosts", "active_tasks", "stale_running"):
            self.assertIn(key, back)

    def test_summary_counts_all_tasks_beyond_detail_limit(self):
        p = self.db()
        _make_db(p, 1000, runs=[(str(i), "running", "w", "review", "x", 900+i) for i in range(15)])
        s = status.collect(db_path=p, now=1000, active_limit=3)
        self.assertEqual(len(s["active_tasks"]), 3)
        self.assertEqual(s["active_counts"]["running"], 15)
        self.assertIn("15 running", status.brief(s)[0])

    def test_job_linked_to_finished_run_still_visible(self):
        p = self.db()
        _make_db(p, 1000, runs=[("r1", "done", "w", "review", "x", 900)],
                 jobs=[("j1", "pending", "", "r1", "waiting", 950)])
        s = status.collect(db_path=p, now=1000)
        self.assertEqual(s["active_counts"]["queued"], 1)
        self.assertEqual(s["active_tasks"][0]["id"], "j1")

    def test_history_keeps_latest_and_stale_running_key(self):
        p = self.db()
        _make_db(p, 100000, runs=[("old", "running", "w", "review", "x", 1),
                                ("new", "done", "w", "review", "x", 99900)])
        s = status.collect(db_path=p, now=100000, per_worker=1)
        self.assertEqual(s["workers"]["w"], ["done"])
        self.assertEqual(s["stale_running"], 1)

    def test_touched_monitor_file_does_not_refresh_old_sample(self):
        p = self.db()
        _make_db(p, 10000)
        _monitor_dir(self.home, [("mac", {"host": "mac", "ts": 1000}, 10000)])
        s = status.collect(db_path=p, now=10000)
        self.assertEqual(s["hosts"]["mac"]["age_s"], 9000)
        self.assertEqual(s["hosts"]["mac"]["freshness"], "stale")


if __name__ == "__main__":
    unittest.main()
