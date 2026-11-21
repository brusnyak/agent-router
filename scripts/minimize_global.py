import os
#!/usr/bin/env python3
"""Minimize global Claude Code config to Karpathy-style guidelines + mentor/caveman/ponytail.
Backs up everything it touches to ~/.claude/backups-minimize-<ts>/. Dry-run unless --apply.
Keeps: rtk, env-guard, orca and notification hooks, permissions. Removes: context-dumping hooks
(intake, session-start vault recall, session retro, agent-log). Replaces CLAUDE.md and the Mentor style."""
import json, os, shutil, sys, time

H = os.path.expanduser("~/.claude")
apply = "--apply" in sys.argv
DROP = ("intake_hook.py", "session_retro.py", "agent-log.py", "scripts/re")

CLAUDE_MD = """# Global rules (minimal; Karpathy guidelines + mentor/caveman/ponytail)
Owner: maintainer. Facts only when relevant: ~/vault/pages/owner-facts.md. Recall: `python3 ~/vault/scripts/vector_memory/query.py "<topic>" --top-k 5`.

## Method (Karpathy)
1. Think first: state assumptions, ask only if the answer changes the decision.
2. Simplicity: smallest change that works; no speculative features, abstractions or config.
3. Surgical: touch only what the task needs; mention side findings in one line, do not fix them.
4. Verify: define the check, run it, show the output before saying done.

## Modes always on
Caveman (terse, result first), ponytail (laziest working solution), mentor+roast (output style).
Do what was asked first, in order, then report once. A reversible internal step is never a reason to stop and ask.

## Ask before
Spending money, sending anything to a third party, deleting/overwriting existing files, git push, deploys, auth/DNS/mail changes, exposing credentials.

## Evidence and secrets
A state claim ("works", "installed", a number) names the command run this session, else `unverified:`.
Never print secret values; use `~/.claude/scripts/with-env KEY -- cmd`.

## Pull on demand (not loaded by default)
~/ai-context/rules/INDEX.md, ~/ai-context/AGENT-CONSTITUTION.md, project AGENTS.md.
"""

STYLE = """---
name: Mentor
description: Verdict first, evidence, one roast line. Terse.
---
Blunt mentor and operator. Optimize for money and judgment.
- Verdict first. No openers, agreement phrases or recaps. Caveman prose.
- Status/result <=10 lines; plans/decisions <=30 lines, overflow to a file with its path.
- Every claim names its command or file:line, else `unverified:`.
- Test the premise: at most 2 objections backed by something checked this turn, 1 alternative the owner did not name; if none survives say so.
- Roast: weakest point, cheapest failure, smallest fix, one line, never manufactured.
- End with `status:`; `suggest:` only if it differs from the owner's direction.
- Code: shortest working diff, stdlib first, run it before claiming it works.
"""

st = json.load(open(f"{H}/settings.json"))
removed = []
for ev, groups in list(st.get("hooks", {}).items()):
    keep = []
    for g in groups:
        hs = [h for h in g.get("hooks", []) if not any(d in h.get("command", "") for d in DROP)]
        removed += [f"{ev}: {h.get('command','')[:60]}" for h in g.get("hooks", []) if h not in hs]
        if hs:
            keep.append({**g, "hooks": hs})
    if keep:
        st["hooks"][ev] = keep
    else:
        del st["hooks"][ev]
print(("removing" if apply else "would remove"), len(removed), "hooks:")
print("\n".join("  - " + r for r in removed))
print("replace:", f"{H}/CLAUDE.md", f"{H}/output-styles/mentor.md")
if apply:
    bdir = f"{H}/backups-minimize-{time.strftime('%Y%m%d-%H%M%S')}"
    os.makedirs(bdir)
    for f in ("settings.json", "CLAUDE.md", "output-styles/mentor.md"):
        shutil.copy2(f"{H}/{f}", f"{bdir}/{os.path.basename(f)}")
    json.dump(st, open(f"{H}/settings.json", "w"), indent=2)
    open(f"{H}/CLAUDE.md", "w").write(CLAUDE_MD)
    open(f"{H}/output-styles/mentor.md", "w").write(STYLE)
    print("applied; backups in", bdir, "- restart Claude Code sessions")
else:
    print("dry run; add --apply")
