import json
import sqlite3

from backbone import digest


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_build_counts_window_and_survives_missing(tmp_path):
    now = 1_000_000.0
    jl(tmp_path / "e", [{"ts": now - 10, "sid": "a", "arm": "treat", "action": "block", "why": "heavy-first-call"},
                        {"ts": now - 5, "sid": "a", "arm": "treat", "action": "allow", "why": "repeat-after-block"},
                        {"ts": now - 90000, "sid": "z", "arm": "treat", "action": "block", "why": "old"}])
    jl(tmp_path / "c", [{"ts": now - 1, "state": "done", "gate": "pytest"}])
    src = {"enforce": str(tmp_path / "e"), "receipts": str(tmp_path / "none"), "router_calls": str(tmp_path / "c"), "nina_hook": str(tmp_path / "none")}
    d = digest.build(24, now=now, sources=src, db=str(tmp_path / "no.db"), bandit=str(tmp_path / "no.db"))
    assert d["enforce"]["events"] == 2 and d["enforce"]["redirects"] == 1 and d["enforce"]["sessions_redirected"] == 1
    assert d["enforce"]["by_arm_action"] == {"treat/block": 1, "treat/allow": 1}
    assert d["nina"]["router_calls"] == 1 and d["receipts"]["prompts"] == 0 and d["runs"] == {} and d["bandit"] == []


def test_runs_and_bandit_tables(tmp_path):
    db = tmp_path / "b.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE runs (worker TEXT, state TEXT, created REAL)")
    c.execute("INSERT INTO runs VALUES ('codex','done',500)")
    c.execute("CREATE TABLE bandit (cls TEXT, worker TEXT, alpha REAL, beta REAL)")
    c.execute("INSERT INTO bandit VALUES ('code_edit','nim1',8,2)")
    c.commit()
    assert digest.runs_summary(str(db), 0) == {"codex/done": 1}
    assert digest.bandit_table(str(db))[0]["mean"] == 0.8


def test_write_is_idempotent(tmp_path):
    p1 = digest.write({"x": 1}, root=str(tmp_path))
    p2 = digest.write({"x": 2}, root=str(tmp_path))
    assert p1 == p2 and json.load(open(tmp_path / "latest.json")) == {"x": 2}
