"""Watcher: one idempotent snapshot of everything router-relevant, written per day and cumulative.
`python3 -m backbone digest [--write] [--hours 24]`. Reads only logs and tables, never prompts: enforce.jsonl (redirect-once hook),
hook-shadow.jsonl (receipts), router-calls.jsonl (Nina's `router vm` calls), router-default.jsonl (Nina's hook), runs table, bandit.
Question it answers after a few days: are heavy tasks going through the router, and is the redirect followed?"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import time

HOME = os.path.expanduser("~")
AR = os.path.join(HOME, ".agent-router")
SOURCES = {
    "enforce": os.path.join(AR, "enforce.jsonl"),
    "receipts": os.path.join(AR, "hook-shadow.jsonl"),
    "router_calls": os.path.join(AR, "router-calls.jsonl"),
    "nina_hook": os.path.join(HOME, ".hermes-nina", "state", "router-default.jsonl"),
}


def read_jsonl(path: str, since: float) -> list:
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if float(r.get("ts", 0)) >= since:
                    out.append(r)
    except OSError:
        pass
    return out


def count(rows, *keys) -> dict:
    return dict(collections.Counter("/".join(str(r.get(k, "")) for k in keys) for r in rows))


def runs_summary(db_path: str, since: float) -> dict:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = con.execute("SELECT worker, state, count(*) FROM runs WHERE created>=? GROUP BY 1,2", (since,)).fetchall()
        return {f"{w}/{s}": n for w, s, n in rows}
    except sqlite3.Error:
        return {}


def bandit_table(path: str) -> list:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        return [{"cls": c, "worker": w, "mean": round(a / (a + b), 3), "n": round(a + b - 10, 1)}
                for c, w, a, b in con.execute("SELECT cls, worker, alpha, beta FROM bandit ORDER BY cls, worker")]
    except sqlite3.Error:
        return []


def build(hours: float = 24.0, now: float | None = None, sources: dict | None = None, db: str = "", bandit: str = "") -> dict:
    now = now or time.time()
    since = now - hours * 3600
    src = sources or SOURCES
    enf, rec = read_jsonl(src["enforce"], since), read_jsonl(src["receipts"], since)
    blocked = [r for r in enf if r.get("action") == "block"]
    calls, nina = read_jsonl(src["router_calls"], since), read_jsonl(src["nina_hook"], since)
    return {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "window_h": hours,
        "enforce": {"events": len(enf), "by_arm_action": count(enf, "arm", "action"), "by_why": count(enf, "why"), "redirects": len(blocked),
                    "sessions_redirected": len({r.get("sid") for r in blocked})},
        "receipts": {"prompts": len(rec), "by_arm": count(rec, "arm"), "heavy_nudged": sum(1 for r in rec if r.get("selected"))},
        "nina": {"router_calls": len(calls), "by_state": count(calls, "state"), "by_gate": count(calls, "gate"), "hook": count(nina, "action", "why")},
        "runs": runs_summary(db or os.path.join(AR, "data", "backbone.db"), since),
        "bandit": bandit_table(bandit or os.environ.get("BANDIT_DB") or os.path.join(AR, "data", "bandit.db")),
    }


def write(d: dict, root: str | None = None) -> str:
    root = root or os.path.join(AR, "digest")
    os.makedirs(root, exist_ok=True)
    day = os.path.join(root, time.strftime("%Y-%m-%d") + ".json")
    with open(day, "w") as f:
        json.dump(d, f, indent=1)
    with open(os.path.join(root, "latest.json"), "w") as f:
        json.dump(d, f, indent=1)
    return day


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="backbone digest")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--write", action="store_true", help="also save ~/.agent-router/digest/<date>.json and latest.json")
    a = ap.parse_args(argv)
    d = build(a.hours)
    if a.write:
        d["file"] = write(d)
    print(json.dumps(d, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
