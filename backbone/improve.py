"""Router-native skill/command improvement loop (Curator-style, evidence-backed).

Reads the outcomes table (gate pass/fail per run) and hook receipts (which
skill/command was surfaced vs actually invoked), then proposes maintenance:
RETIRE (never used, no demand), MERGE (near-duplicate names/descriptions),
UPDATE (high demand, low success — rewrite description/trigger), PROMOTE
(high success, low usage — surface more aggressively), KEEP.

Propose-only: writes a report, never touches skills/agents/commands. Owner
applies via `backbone librarian`/manual edit after review.

Smart-lazy: reuses the existing outcomes table (graph.finish() records every
run), hook receipts (hook-shadow.jsonl), and the library catalog. No LLM
calls, no network, stdlib + sqlite.
"""
from __future__ import annotations

import json, math, os, re, time
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .db import DB

HOME = os.path.expanduser("~")
AR = os.path.join(HOME, ".agent-router")
RECEIPTS = os.path.join(AR, "hook-shadow.jsonl")
OUTCOMES_DB = os.path.join(AR, "data", "backbone.db")

RETIRE_STALE_DAYS = 90
LOW_SUCCESS = 0.50
HIGH_SUCCESS = 0.80
MIN_USE = 3


def _read_jsonl(path: str) -> List[dict]:
    out: List[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def _tok(s: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _cos(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    inter = sum((a & b).values())
    if inter == 0:
        return 0.0
    return inter / math.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))


def catalog_rows(con) -> List[dict]:
    """All library rows: kind, name, description, updated."""
    rows = con.execute(
        "SELECT kind, name, description, updated FROM library"
    ).fetchall()
    return [dict(kind=r[0], name=r[1], description=r[2] or "", updated=r[3] or 0)
            for r in rows]


def usage_from_receipts(receipts: List[dict]) -> Counter:
    """Count how often each skill/command was selected/surfaced to the model."""
    c: Counter = Counter()
    for r in receipts:
        for name in (r.get("selected") or []) + (r.get("would_surface") or []):
            if name:
                c[name] += 1
    return c


def outcomes_by_route(con) -> Dict[str, dict]:
    """Per (task_class, route) acceptance stats from the outcomes table."""
    try:
        rows = con.execute(
            "SELECT task_class, route, ok, latency_ms FROM outcomes"
        ).fetchall()
    except Exception:
        return {}
    stats: Dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "lat": []})
    for cls, route, ok, lat in rows:
        key = f"{cls or 'other'}/{route or 'unknown'}"
        st = stats[key]
        st["n"] += 1
        if ok:
            st["wins"] += 1
        if lat:
            st["lat"].append(int(lat))
    out: Dict[str, dict] = {}
    for key, st in stats.items():
        med = 0
        if st["lat"]:
            sl = sorted(st["lat"])
            med = sl[len(sl) // 2]
        out[key] = {
            "n": st["n"], "wins": st["wins"],
            "accept": round(st["wins"] / st["n"], 3) if st["n"] else 0.0,
            "median_latency_ms": med,
        }
    return out


def nearest_neighbour_all(cat: List[dict], toks: List[Counter]) -> List[tuple[Optional[str], float]]:
    """Nearest other catalog entry by name+description cosine for every entry.
    Precomputes tokens once; O(n^2) but on small token sets (names+descriptions).
    """
    out: List[tuple[Optional[str], float]] = []
    norms = [math.sqrt(sum(v * v for v in t.values())) for t in toks]
    for i, a in enumerate(toks):
        best_name, best_score = None, 0.0
        na = norms[i]
        for j, b in enumerate(toks):
            if j == i or norms[j] == 0 or na == 0:
                continue
            inter = sum((a & b).values())
            if inter == 0:
                continue
            score = inter / (na * norms[j])
            if score > best_score:
                best_score = score
                best_name = cat[j]["name"]
        out.append((best_name, best_score))
    return out


def improve(con: DB, receipts: List[dict], top_n: int = 40) -> List[dict]:
    """Return a list of improvement proposals, each a dict."""
    cat = catalog_rows(con._c)
    usage = usage_from_receipts(receipts)
    outcomes = outcomes_by_route(con._c)
    # nearest-neighbour (cosine) computed lazily only for KEEP candidates that
    # might become MERGE proposals; avoids O(n^2) over the full catalog.
    _nn_cache: Dict[int, tuple[Optional[str], float]] = {}

    def nn(i: int) -> tuple[Optional[str], float]:
        if i not in _nn_cache:
            _nn_cache[i] = nearest_neighbour(cat, i)
        return _nn_cache[i]

    proposals: List[dict] = []
    for i, e in enumerate(cat):
        name = e["name"]
        kind = e["kind"]
        u = usage[name]
        route_stats = None
        for key, st in outcomes.items():
            if key.endswith("/" + name):
                route_stats = st
                break
        accept = route_stats["accept"] if route_stats else None
        n_out = route_stats["n"] if route_stats else 0
        age = (time.time() - e["updated"]) / 86400 if e["updated"] else None

        if u == 0 and n_out == 0:
            if age is not None and age > RETIRE_STALE_DAYS:
                prop, flag = "RETIRE", "no usage or demand, stale"
            else:
                prop, flag = "RETIRE", "no usage or demand"
        elif accept is not None and n_out >= MIN_USE:
            if accept < LOW_SUCCESS:
                prop, flag = "UPDATE", f"high demand ({n_out}) but low acceptance {accept:.0%}"
            elif accept >= HIGH_SUCCESS and u < 2:
                prop, flag = "PROMOTE", f"high acceptance {accept:.0%} but rarely surfaced ({u}x)"
            else:
                prop, flag = "KEEP", ""
        elif accept is not None and accept < LOW_SUCCESS:
            prop, flag = "UPDATE", f"low acceptance {accept:.0%}"
        else:
            prop, flag = "KEEP", ""

        nearest, nn_cos = "-", 0.0
        if prop == "KEEP":
            nearest, nn_cos = nn(i)
            if nn_cos >= 0.45:
                prop, flag = "MERGE", f"near-duplicate of '{nearest}' (cos {nn_cos:.2f})"

        proposals.append({
            "kind": kind, "name": name,
            "usage": u, "outcomes_n": n_out, "accept": round(accept, 3) if accept is not None else None,
            "nearest": nearest, "cos": round(nn_cos, 2),
            "age_days": int(age) if age is not None else -1,
            "proposal": prop, "flag": flag,
        })

    prio = {"RETIRE": 0, "UPDATE": 1, "MERGE": 2, "PROMOTE": 3, "KEEP": 4}
    proposals.sort(key=lambda p: (prio.get(p["proposal"], 5), -p["usage"]))
    return proposals[:top_n]


def format_report(props: List[dict]) -> str:
    lines = ["# Router skill/command improvement report (propose-only)",
             "| kind | name | usage | outcomes | accept | nearest | cos | age | proposal | flag |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for p in props:
        lines.append("| %s | %s | %d | %d | %s | %s | %s | %d | %s | %s |" % (
            p["kind"], p["name"], p["usage"], p["outcomes_n"],
            p["accept"] if p["accept"] is not None else "-",
            p["nearest"], p["cos"], p["age_days"], p["proposal"], p["flag"]))
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    import argparse, sqlite3
    ap = argparse.ArgumentParser(prog="backbone improve")
    ap.add_argument("--receipts", default=RECEIPTS)
    ap.add_argument("--db", default=OUTCOMES_DB)
    ap.add_argument("--out", default=os.path.join(AR, "improve-report.md"))
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args(argv)
    receipts = _read_jsonl(a.receipts)
    try:
        con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
    except Exception as e:
        print(f"cannot open db {a.db}: {e}", file=__import__("sys").stderr)
        return 1
    db = DB(con)
    props = improve(db, receipts, top_n=a.top)
    report = format_report(props)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    print(f"\nwrote {a.out} ({len(props)} proposals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
