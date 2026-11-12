#!/usr/bin/env python3
"""Surgical: remove caveman hook entries (and ANTHROPIC_BASE_URL if it points at the caveman proxy) from
~/.claude/settings.json. Dry-run by default; --apply writes a timestamped backup first. Nothing else is touched."""
import json, os, re, shutil, sys, time

P = os.path.expanduser("~/.claude/settings.json")
apply = "--apply" in sys.argv
d = json.load(open(P))
removed = []
for ev, groups in list(d.get("hooks", {}).items()):
    keep = []
    for g in groups:
        hs = [h for h in g.get("hooks", []) if "caveman" not in h.get("command", "").lower()]
        removed += [f"{ev}: {h.get('command','')[:70]}" for h in g.get("hooks", []) if h not in hs]
        if hs:
            keep.append({**g, "hooks": hs})
    if keep:
        d["hooks"][ev] = keep
    else:
        del d["hooks"][ev]
env = d.get("env", {})
if "8788" in str(env.get("ANTHROPIC_BASE_URL", "")):
    removed.append("env.ANTHROPIC_BASE_URL (caveman proxy)")
    env.pop("ANTHROPIC_BASE_URL", None)
    env.pop("_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL", None)
left = len(re.findall("caveman", json.dumps(d), re.I))
print(f"would remove {len(removed)} entries:" if not apply else f"removed {len(removed)} entries:")
print("\n".join("  - " + r for r in removed))
print(f"remaining 'caveman' mentions after change: {left} (permissions/skills lines are harmless)")
if apply:
    bak = f"{P}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(P, bak)
    json.dump(d, open(P, "w"), indent=2)
    print("backup:", bak)
else:
    print("dry run. Re-run with --apply. Restart Claude Code sessions afterwards.")
