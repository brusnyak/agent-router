"""Fixed, read-only Mac collector. No model-authored commands, tools or sends."""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from .workers import Result
from .workspace import run_group


ROOT = Path.home() / 'Documents/Acore/Development/career-agent'
CHILD = '''import json
from career_agent import livegate as g
profile = g.load_profile()
rows = []
for r in g.run_djinni(profile, 8, ""):
    r["skills"] = g.overlap(r["text"], g.skills_of(profile))
    r["text"] = r["text"][:6000] if r["ok"] else ""
    rows.append(r)
print(json.dumps({"seen":len(rows),"passed":sum(r["ok"] for r in rows),"postings":rows}, ensure_ascii=False))
'''


def available():
    return sys.platform == 'darwin' and (ROOT / '.venv/bin/python').exists() and Path('/usr/bin/sandbox-exec').exists()


def run(*, idle=False):
    if not available():
        return Result(False, 'career collector unavailable on this host', 'career-scan')
    if idle:
        from .idle_policy import current_snapshot, decision
        why = decision(current_snapshot())
        if why != 'ready':
            return Result(False, f'idle gate: {why}', 'career-scan')
    cmd = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny file-write*)',
           str(ROOT / '.venv/bin/python'), '-B', '-c', CHILD]
    env = {'HOME':str(Path.home()),'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
           'PYTHONPATH':str(ROOT/'src'), 'PYTHONDONTWRITEBYTECODE':'1', 'BACKBONE_WATCH_PAUSE':'1'}
    if idle: env['BACKBONE_WATCH_IDLE']='1'
    try:
        p = run_group(cmd, str(ROOT), 120, env=env)
    except Exception as e:
        return Result(False, f'collector stopped: {type(e).__name__}: {str(e)[:180]}', 'career-scan')
    evidence = {'kind':'career-public-scan','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'read_only_sandbox':True,'idle_enforced':idle,'exit_code':p.returncode,
                'candidates':p.stdout[-12000:],'qualification_counts':p.stderr[-1800:]}
    return Result(p.returncode == 0, json.dumps(evidence,ensure_ascii=False), 'career-scan')
