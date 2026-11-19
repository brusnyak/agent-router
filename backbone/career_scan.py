"""Fixed, read-only Mac collector. No model-authored commands, tools or sends.

root/profile_path come ONLY from trusted host config (cfg.workers.career-scan), never from model-authored options.
Without host config the legacy checkout location is used, so existing installs keep working.
"""
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from .workers import Result
from .workspace import run_group


ROOT = Path.home() / 'Documents/Acore/Development/career-agent'   # legacy default until host config sets root
MAX_POSTINGS = 3          # result budget: at most this many postings reach the caller
TEXT_CAP = 800            # per-posting description cap (chars); full text must be fetched before any outward copy
FIELD_CAP = 300           # cap for other string fields; a capped field sets fields_truncated
LIST_CAP = 20
SKILL_CAP = 60            # per-skill string cap; skills are bounded strings only
MAX_SEEN = 8              # child row cap; seen/passed beyond this are rejected
STR_FIELDS = ('title', 'url', 'why', 'source', 'observed_at')   # copied to output when str; everything else dropped
MAX_STDOUT = 200_000      # child is bounded to 8 rows x 6000 text; anything larger is rejected
MAX_RESULT = 6000         # chars of the final Result.text
CHILD = '''import json, os
from pathlib import Path
from career_agent import livegate as g
pp = os.environ.get('CAREER_PROFILE_PATH')
profile = g.load_profile(Path(pp)) if pp else g.load_profile()
rows = []
for r in g.run_djinni(profile, 8, ""):
    r["skills"] = g.overlap(r["text"], g.skills_of(profile))
    r["text"] = r["text"][:6000] if r["ok"] else ""
    rows.append(r)
print(json.dumps({"seen":len(rows),"passed":sum(r["ok"] for r in rows),"postings":rows}, ensure_ascii=False))
'''


def available(root=None):
    base = _expand(root) or ROOT
    return sys.platform == 'darwin' and (base / '.venv/bin/python').exists() and Path('/usr/bin/sandbox-exec').exists()


def _expand(value):
    return Path(os.path.expanduser(str(value))) if value else None


def _blocked(reason, now, idle, exit_code=None):
    evidence = {'kind':'career-public-scan','observed_at':now,'read_only_sandbox':True,'idle_enforced':idle,
                'status':'blocked','reason':reason}
    if exit_code is not None:
        evidence['exit_code'] = exit_code
    return Result(False, json.dumps(evidence, ensure_ascii=False), 'career-scan')


def _parse(stdout):
    """Complete child JSON with a valid schema, or None."""
    if len(stdout) > MAX_STDOUT:
        return None
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    seen, passed, rows = data.get('seen'), data.get('passed'), data.get('postings')
    if not (_is_int(seen) and _is_int(passed)) or not (0 <= passed <= seen <= MAX_SEEN):
        return None
    if not isinstance(rows, list) or len(rows) != seen:
        return None
    for r in rows:
        if not (isinstance(r, dict) and isinstance(r.get('ok'), bool)
                and isinstance(r.get('title'), str) and isinstance(r.get('url'), str)
                and isinstance(r.get('text', ''), str)):
            return None
    if passed != sum(1 for r in rows if r['ok']):
        return None
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _shrink(row, text_cap):
    """Known flat fields only. Nested payloads and unknown keys are never copied."""
    out, fields_truncated = {'ok': row['ok']}, False
    for k in STR_FIELDS:
        v = row.get(k)
        if isinstance(v, str):
            if len(v) > FIELD_CAP:
                v, fields_truncated = v[:FIELD_CAP], True
            out[k] = v
    skills, kept_skills = row.get('skills'), []
    if isinstance(skills, list):
        if len(skills) > LIST_CAP:
            fields_truncated = True
        for s in skills[:LIST_CAP]:
            if isinstance(s, str):
                if len(s) > SKILL_CAP:
                    s, fields_truncated = s[:SKILL_CAP], True
                kept_skills.append(s)
    out['skills'] = kept_skills
    text = row.get('text', '') or ''
    out['text'] = text[:text_cap]
    out['description_truncated'] = len(text) > text_cap
    out['full_description_required'] = True   # clipped or not, the full posting is needed before outward copy
    out['fields_truncated'] = fields_truncated
    return out


def _bounded(base, rows):
    """Serialize within MAX_RESULT by shrinking text first, then dropping postings. None if nothing fits.
    Passed rows are selected before rejected rows; stable order within each group."""
    ordered = sorted(rows, key=lambda r: not r['ok'])
    for text_cap in (TEXT_CAP, 300, 0):
        kept = [_shrink(r, text_cap) for r in ordered[:MAX_POSTINGS]]
        text = json.dumps(dict(base, postings=kept, omitted_postings=len(rows) - len(kept)), ensure_ascii=False)
        if len(text) <= MAX_RESULT:
            return text
    text = json.dumps(dict(base, postings=[], omitted_postings=len(rows)), ensure_ascii=False)
    return text if len(text) <= MAX_RESULT else None


def run(*, idle=False, root=None, profile_path=None):
    """root / profile_path: trusted host config only (cfg.workers.career-scan)."""
    if not available(root):
        return Result(False, 'career collector unavailable on this host', 'career-scan')
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if idle:
        from .idle_policy import current_snapshot, decision
        why = decision(current_snapshot())
        if why != 'ready':
            return Result(False, f'idle gate: {why}', 'career-scan')
    base_root = _expand(root) or ROOT
    profile = _expand(profile_path)
    cmd = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny file-write*)',
           str(base_root / '.venv/bin/python'), '-B', '-c', CHILD]
    env = {'HOME':str(Path.home()),'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
           'PYTHONPATH':str(base_root/'src'), 'PYTHONDONTWRITEBYTECODE':'1', 'BACKBONE_WATCH_PAUSE':'1'}
    if idle: env['BACKBONE_WATCH_IDLE']='1'
    if profile: env['CAREER_PROFILE_PATH'] = str(profile)
    try:
        p = run_group(cmd, str(base_root), 120, env=env)
    except Exception as e:
        return Result(False, f'collector stopped: {type(e).__name__}: {str(e)[:180]}', 'career-scan')
    if p.returncode != 0:
        return _blocked('collector exited nonzero', now, idle, p.returncode)
    data = _parse(p.stdout)
    if data is None:
        return _blocked('collector output invalid', now, idle, p.returncode)
    if data['seen'] == 0:   # empty or unavailable source: not claimed either way
        return _blocked('no observed postings', now, idle, p.returncode)
    base = {'kind':'career-public-scan','observed_at':now,'read_only_sandbox':True,'idle_enforced':idle,
            'exit_code':p.returncode,'status':'ok','seen':data['seen'],'passed':data['passed'],
            'qualification_counts':(p.stderr or '')[-600:]}
    text = _bounded(base, data['postings'])
    if text is None:
        return _blocked('collector result exceeds budget', now, idle, p.returncode)
    return Result(True, text, 'career-scan')
