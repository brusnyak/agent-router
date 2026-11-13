"""Spot-check cards: real context around silver items, for human review. Private output -> file only, never stdout.
Assumed schemas (unverified; data dir absent in worktree): dev/test rows {id,prompt,label,candidates?};
judge rows {id,label,why}; catalog.json {name: desc} or [{name,description}]."""
from __future__ import annotations

import glob
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mine_transcripts import SECRET, human_text  # noqa: E402

H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "heldout_v2")
RELAY = "Another Claude session sent"


def jl(path):
    out = []
    for line in open(path, encoding="utf-8", errors="replace") if os.path.exists(path) else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def atext(m):
    c = m.get("message", {}).get("content")
    if isinstance(c, str):
        return c
    return " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")


def tools(m):
    c = m.get("message", {}).get("content")
    return [b["name"] for b in c or [] if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name")]


def clean(s, n):
    s = " ".join(ln for ln in s.splitlines() if not SECRET.search(ln)).strip()
    return s[:n]


def context(prompt, root):
    """Find the user message equal to prompt; return (project, prev assistant text, (next tools, next text))."""
    for path in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        msgs = [m for m in jl(path) if not m.get("isSidechain")]
        for i, m in enumerate(msgs):
            if m.get("type") == "user" and human_text(m) == prompt:
                prev = next((atext(x) for x in reversed(msgs[:i]) if x.get("type") == "assistant" and atext(x).strip()), "")
                names, txt = [], ""
                for x in msgs[i + 1:]:
                    if x.get("type") == "user" and human_text(x):
                        break
                    if x.get("type") == "assistant":
                        names += tools(x)
                        txt = txt or atext(x)
                return os.path.basename(os.path.dirname(path)), prev, (names[:5], txt)
    return None


def load_catalog(path):
    c = json.load(open(path)) if os.path.exists(path) else {}
    if isinstance(c, list):
        c = {x.get("name"): x.get("description", "") for x in c if isinstance(x, dict)}
    return c


def build(n=30, seed=0, root=None, h=H, out=None):
    root = root or os.path.expanduser("~/.claude/projects")
    items = [r for f in ("dev", "test") for r in jl(f"{h}/{f}.jsonl")
             if not r.get("prompt", "").startswith(RELAY) and not SECRET.search(r.get("prompt", ""))]
    random.Random(seed).shuffle(items)
    judges = {}
    for p in sorted(glob.glob(f"{h}/judge/sonnet_*.jsonl") + glob.glob(f"{h}/judge/nim.jsonl") + glob.glob(f"{h}/judge/haiku_0*.jsonl")):
        for r in jl(p):
            judges.setdefault(r.get("id"), []).append((os.path.basename(p)[:-6], r.get("label"), r.get("why", "")))
    cat = load_catalog(f"{h}/judge/catalog.json")
    cards = []
    for it in items:
        if len(cards) >= n:
            break
        ctx = context(it["prompt"], root)
        if not ctx:
            continue
        proj, prev, (names, ntxt) = ctx
        c = [f"## {len(cards) + 1}. {it.get('id')} ({proj})", f"**Previous assistant:** {clean(prev, 300)}",
             f"**User:** {clean(it['prompt'], 500)}", f"**Next action:** tools={names} | {clean(ntxt, 200)}", "**Judges:**"]
        c += [f"- {j}: {lab} — {clean(str(w), 200)}" for j, lab, w in judges.get(it.get("id"), [])]
        c.append("**Top-3 candidates:**")
        c += [f"- {k}: {clean(str(cat.get(k, '')), 150)}" for k in (it.get("candidates") or [])[:3]]
        c += [f"**Q:** Would a hint for `{it.get('label')}` have helped here? yes / no / unsure", "better label: ", ""]
        cards.append("\n".join(c))
    out = out or f"{h}/spotcheck_cards.md"
    open(out, "w", encoding="utf-8").write("\n".join(cards))
    return len(cards)


if __name__ == "__main__":
    k = build(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
    print(f"{k} cards written")
