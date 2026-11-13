"""Regenerate the routing catalog deterministically from the skills/agents inventory.

Dry-run by default (counts + diff vs existing file); --write to save.
"""
import argparse
import json
import re
from pathlib import Path

HOME = Path.home() / ".claude"
DEFAULT_OUT = Path(__file__).parent / "heldout_v2" / "judge" / "catalog.json"
CAP = 300


def _unq(s):
    s = s.strip()
    while len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def _front(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"\A---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    out, key = {}, None
    for line in m.group(1).splitlines():
        kv = re.match(r"^(name|description):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            out[key] = kv.group(2)
        elif key and line[:1] in " \t" and line.strip():
            out[key] += " " + line.strip()  # folded continuation
        else:
            key = None
    return out if out.get("name") else None


def collect(skills_dir, agents_dir):
    files = [("skill", p) for p in sorted(Path(skills_dir).glob("*/SKILL.md"))]
    files += [("agent", p) for p in sorted(Path(agents_dir).glob("*.md"))]
    seen = {}
    for kind, p in files:
        if not p.exists():  # broken symlink
            continue
        fm = _front(p)
        if not fm:
            continue
        name = _unq(fm["name"])
        desc = _unq(fm.get("description", ""))[:CAP]
        seen.setdefault((kind, name), {"kind": kind, "name": name, "desc": desc})
    return [seen[k] for k in sorted(seen)]


def render(items):
    return json.dumps(items, indent=2, ensure_ascii=False) + "\n"


def diff(old, new):
    o = {(i["kind"], i["name"]): i["desc"] for i in old}
    n = {(i["kind"], i["name"]): i["desc"] for i in new}
    return (sorted(n.keys() - o.keys()), sorted(o.keys() - n.keys()),
            sorted(k for k in o.keys() & n.keys() if o[k] != n[k]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills-dir", default=str(HOME / "skills"))
    ap.add_argument("--agents-dir", default=str(HOME / "agents"))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    items = collect(a.skills_dir, a.agents_dir)
    out = Path(a.out)
    if a.write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(items), encoding="utf-8")
        print(f"wrote {len(items)} -> {out}")
        return 0
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    added, removed, changed = diff(old, items)
    print(f"new={len(items)} existing={len(old)}")
    for label, ks in (("added", added), ("removed", removed), ("changed", changed)):
        print(f"{label}({len(ks)}): " + ", ".join(f"{k}:{n}" for k, n in ks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
