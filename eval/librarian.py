"""Offline catalog librarian. Propose-only: writes a report, never touches skills/agents."""
import argparse, glob, json, math, os, re, time
from collections import Counter
from datetime import date

PROTECTED_PAIRS = {("research", "researcher")}
STALE_DAYS = 180  # assumption: UPDATE-CHECK = used, regular file, untouched this long


def norm(s):
    return str(s).strip("\"'")


def _tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def usage_counts(projects_glob):
    c = Counter()
    for p in glob.glob(projects_glob):
        try:
            for line in open(p, errors="ignore"):
                if '"tool_use"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                content = (obj.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                        continue
                    inp = b.get("input") or {}
                    if b.get("name") == "Skill":
                        n = inp.get("skill")
                    elif b.get("name") in ("Agent", "Task"):
                        n = inp.get("subagent_type")
                    else:
                        n = None
                    if n:
                        c[norm(n)] += 1
        except OSError:
            pass
    return c


def demand_counts(judge_dir):
    c = Counter()
    for p in glob.glob(os.path.join(judge_dir, "sonnet_*.jsonl")):
        for line in open(p, errors="ignore"):
            try:
                lab = norm(json.loads(line).get("label") or "")
            except (ValueError, AttributeError):
                continue
            if lab and lab.lower() != "none":
                c[lab] += 1
    return c


def neighbours(entries):
    docs = [Counter(_tok(e["name"] + " " + e["desc"])) for e in entries]
    df = Counter(t for d in docs for t in d)
    n = len(docs)
    vecs = []
    for d in docs:
        v = {t: f * math.log((1 + n) / (1 + df[t])) for t, f in d.items()}
        nm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / nm for t, x in v.items()})
    out = []
    for i, a in enumerate(vecs):
        best, bs = None, 0.0
        for j, b in enumerate(vecs):
            pair = (entries[i]["name"], entries[j]["name"])
            if i == j or pair in PROTECTED_PAIRS or pair[::-1] in PROTECTED_PAIRS:
                continue
            s = sum(x * b.get(t, 0.0) for t, x in a.items())
            if s > bs:
                best, bs = entries[j]["name"], s
        out.append((best, bs))
    return out


def path_for(home, e):
    if e["kind"] == "skill":
        return os.path.join(home, "skills", e["name"], "SKILL.md")
    return os.path.join(home, "agents", e["name"] + ".md")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="eval/heldout_v2/judge/catalog.json")
    ap.add_argument("--judge-dir", default="eval/heldout_v2/judge")
    ap.add_argument("--claude-home", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--out-dir", default="research")
    a = ap.parse_args(argv)

    entries = [{"kind": norm(e["kind"]), "name": norm(e["name"]), "desc": e.get("desc", "")}
               for e in json.load(open(a.catalog))]
    use = usage_counts(os.path.join(a.claude_home, "projects", "*", "*.jsonl"))
    dem = demand_counts(a.judge_dir)
    rows = []
    for e, (nn, cos) in zip(entries, neighbours(entries)):
        u, d = use[e["name"]], dem[e["name"]]
        p = path_for(a.claude_home, e)
        link = os.path.islink(p)
        age = (time.time() - os.stat(p).st_mtime) / 86400 if os.path.exists(p) else None
        flag = ""
        if u == 0 and d == 0:
            prop = "RETIRE"
        elif d >= 8 and u <= 2:
            prop, flag = "KEEP", "activation-gap"
        elif nn and cos >= 0.40:
            prop = "MERGE(%s)" % nn
        elif u > 0 and not link and age is not None and age > STALE_DAYS:
            prop = "UPDATE-CHECK"
        elif d > 0 and not os.path.lexists(p):
            prop = "ACQUIRE-GAP"
        else:
            prop = "KEEP"
        rows.append("| %s | %s | %d | %d | %s | %.2f | %s | %s | %s | %s |" % (
            e["kind"], e["name"], u, d, nn or "-", cos,
            "-" if age is None else int(age), "yes" if link else "no", prop, flag))
    os.makedirs(a.out_dir, exist_ok=True)
    out = os.path.join(a.out_dir, "librarian-%s.md" % date.today().isoformat())
    with open(out, "w") as f:
        f.write("# Librarian report (propose-only; no files touched)\n\n"
                "| kind | name | usage | demand | nearest | cos | age_days | symlink | proposal | flag |\n"
                "|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
