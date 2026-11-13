"""Receipt + outcome logging and the treat-vs-holdout report.

Behavior modelled on third_party/meta-router/cmd/mr-outcomes/main.go (outcome join)
and cmd/mr-hook/holdout.go (treat/holdout arms), Apache-2.0. Those files were NOT
present in this worktree, so no file:line cites; written independently from the spec.
"followed = agreement, not effect": a followed prompt is not proof the hook caused it.
"""
import argparse, json, math, os, sys, time
from collections import defaultdict

LABEL = "followed = agreement, not effect"
ARMS = ("treat", "holdout", "none")
MIN_N = 20
HOME = os.path.expanduser("~/.agent-router")
RECEIPTS = os.path.join(HOME, "hook-shadow.jsonl")
OUTCOMES = os.path.join(HOME, "outcomes.jsonl")


def load(path):
    """Read JSONL; skip unparseable/non-object lines. Returns (rows, bad_count)."""
    rows, bad = [], 0
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return rows, bad
    with f:
        for line in f:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(r, dict):
                rows.append(r)
            else:
                bad += 1
    return rows, bad


def append_outcome(path, skill, session_id, prompt_id, tool_use_id, ts=None):
    """PostToolUse helper: append one outcome row."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    row = {"ts": time.time() if ts is None else ts, "skill": skill,
           "session_id": session_id, "prompt_id": prompt_id, "tool_use_id": tool_use_id}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _le(a, b):
    try:
        return a <= b
    except TypeError:
        return False


def join(receipts, outcomes):
    """-> (receipt_id -> [outcomes], skipped_no_session).

    Outcome goes to the receipt with the same prompt_id; else (no prompt_id) to the
    latest receipt of the same session_id with ts <= outcome ts. No session_id =>
    skipped, never attributed.
    """
    by_pid = {r["prompt_id"]: r for r in receipts if r.get("prompt_id")}
    by_sid = defaultdict(list)
    for r in receipts:
        if r.get("session_id") and "ts" in r:
            by_sid[r["session_id"]].append(r)
    out, skipped = defaultdict(list), 0
    for o in outcomes:
        if not o.get("session_id"):
            skipped += 1
            continue
        if o.get("prompt_id"):
            r = by_pid.get(o["prompt_id"])
        else:
            cands = [c for c in by_sid.get(o["session_id"], []) if _le(c["ts"], o.get("ts"))]
            r = max(cands, key=lambda c: c["ts"]) if cands else None
        if r is not None:
            out[r.get("receipt_id")].append(o)
    return out, skipped


def followed(receipt, outcomes_for_it):
    names = set(receipt.get("selected") or []) | set(receipt.get("would_surface") or [])
    return any(o.get("skill") in names for o in outcomes_for_it)


def _p_value(f1, n1, f2, n2):
    """Two-sided pooled two-proportion z-test (normal approx via math.erf)."""
    p = (f1 + f2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (f1 / n1 - f2 / n2) / se
    return 1 - math.erf(abs(z) / math.sqrt(2))


def report(receipts, outcomes, bad_lines=0):
    attributed, skipped = join(receipts, outcomes)
    arms = {a: {"prompts": 0, "followed": 0} for a in ARMS}
    for r in receipts:
        a = r.get("arm") if r.get("arm") in arms else "none"
        arms[a]["prompts"] += 1
        arms[a]["followed"] += followed(r, attributed.get(r.get("receipt_id"), []))
    for s in arms.values():
        s["rate"] = s["followed"] / s["prompts"] if s["prompts"] else None
    t, h = arms["treat"], arms["holdout"]
    insufficient = t["prompts"] < MIN_N or h["prompts"] < MIN_N
    diff = p = None
    if not insufficient:
        diff = (t["rate"] - h["rate"]) * 100
        p = _p_value(t["followed"], t["prompts"], h["followed"], h["prompts"])
    return {"arms": arms, "treat_minus_holdout_pp": diff, "p_value": p,
            "insufficient": insufficient, "skipped_no_session": skipped,
            "bad_lines": bad_lines, "label": LABEL}


def format_report(rep):
    def na(v, fmt):
        return "n/a" if v is None else fmt % v
    lines = [rep["label"]]
    for a, s in rep["arms"].items():
        lines.append("%-8s prompts=%d followed=%d rate=%s" % (a, s["prompts"], s["followed"], na(s["rate"], "%.3f")))
    lines.append("treat-holdout (pp): " + na(rep["treat_minus_holdout_pp"], "%.1f"))
    lines.append("p-value: " + na(rep["p_value"], "%.4f"))
    if rep["insufficient"]:
        lines.append("insufficient: need >= %d prompts in treat and holdout" % MIN_N)
    lines.append("skipped_no_session=%d bad_lines=%d" % (rep["skipped_no_session"], rep["bad_lines"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="backbone.hook_log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--receipts", default=RECEIPTS)
    rp.add_argument("--outcomes", default=OUTCOMES)
    rp.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rec, b1 = load(a.receipts)
    out, b2 = load(a.outcomes)
    rep = report(rec, out, b1 + b2)
    print(json.dumps(rep, indent=2) if a.json else format_report(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
