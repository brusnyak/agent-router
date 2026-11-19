"""Skill picker for the UserPromptSubmit hook. Stdlib only, no network.

BM25 over name + description (+ triggers when the row has them); the body is NOT searched (it let long generic bodies win
on common words). Abstains unless: >= MIN_MATCH distinct content terms matched, score >= FLOOR, and the winner beats the
runner-up by MARGIN. Only kinds in KINDS are ever injected."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Optional, Tuple

KINDS = ("skill", "agent", "subagent", "command")
MIN_MATCH = 2
RARE_DF = 8
FLOOR = 16.0
MARGIN = 1.10
KIND_PRIOR = {"skill": 1.0, "subagent": 0.92, "agent": 0.92, "command": 0.85}   # same topic in several kinds: prefer the skill
K1, B = 1.5, 0.75
STOP = frozenset("""the and for with that this from have has are was were you your not but can could would should will just
into out all any one two use using used get got let make made need needs want wants like also then than them they their what
when where which who why how too very more most some such only own same other its our about after again before below above
over under here there these those been being does did doing done itself myself please thanks thank yes okay sure now still
run check show tell ask think restart move kill fix continue explain summarize validate rename better worse good great right wrong
question questions time sounds sound looks look logs commit first second third alright sure know mean means said say let lets
already really maybe actually basically essentially kind sort thing things stuff lot lots way ways even much many""".split())


def tokens(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[a-z0-9]{3,}", (text or "").lower()):
        if w in STOP:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _doc(row: dict) -> Counter:
    c: Counter = Counter()
    for field, weight in (("name", 3), ("description", 2), ("triggers", 2)):
        v = row.get(field) or ""
        for t in tokens(" ".join(v) if isinstance(v, list) else str(v)):
            c[t] += weight
    return c


FOLLOWUP = re.compile(r"^\s*(\d+[.)]\s|no\b|nope\b|yes\b|yeah\b|sure\b|ok(ay)?\b|right\b|alright\b|and\b|but\b|also\b|so\b|well\b|hmm)", re.I)


def pick(index: List[dict], prompt: str) -> Optional[Tuple[dict, float, str]]:
    """-> (row, score, why) or None when nothing is clearly relevant."""
    if FOLLOWUP.match(prompt):          # a reply inside a running conversation: its topic lives in earlier turns, not in these words
        return None
    q = sorted(set(tokens(prompt)))
    if not q:
        return None
    rows = [r for r in index if (r.get("kind") or "skill") in KINDS]
    docs = [_doc(r) for r in rows]
    n = len(docs) or 1
    avg = sum(sum(d.values()) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in d)
    scored = []
    for row, d in zip(rows, docs):
        length, matched, s, rare_name, name_hit = sum(d.values()), 0, 0.0, False, False
        names = set(tokens(row.get("name") or ""))
        for t in q:
            f = d.get(t, 0)
            if not f:
                continue
            matched += 1
            name_hit = name_hit or t in names
            rare_name = rare_name or (t in names and df[t] <= RARE_DF)   # one rare term in the name (fastapi, hipaa) is enough
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * (K1 + 1) / (f + K1 * (1 - B + B * length / avg))
        if matched and name_hit:   # a topic word must appear in the NAME: body/description-only overlap is how generic skills won
            scored.append((s * KIND_PRIOR.get(row.get("kind"), 1.0), matched if matched >= MIN_MATCH or not rare_name else MIN_MATCH, row))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return None
    s, matched, row = scored[0]
    if matched < MIN_MATCH:
        return None
    if s < FLOOR:
        return None
    win = set(tokens(row.get("name") or ""))
    same = lambda r: bool(win & set(tokens(r.get("name") or "")))       # same-topic siblings (skill/agent/command) are not rivals
    rivals = [x for x in scored[1:] if not same(x[2])]
    if rivals and s < MARGIN * rivals[0][0]:
        return None
    for s2, m2, r2 in scored[1:]:                                       # same topic: prefer the skill when it is close
        if r2.get("kind") == "skill" and row.get("kind") != "skill" and same(r2) and s2 >= 0.9 * s:
            s, row = s2, r2
            break
    return row, s, f"bm25={s:.1f} matched={matched}/{len(q)}"


GENERIC = frozenset("pattern developer expert specialist architect test testing review reviewer engineer guide practice agent writer builder".split())


def same_topic(name: str, ok: List[str]) -> bool:
    """A pick is right when it is an expected name or shares a topic word with one (kubernetes-specialist ~ kubernetes-patterns)."""
    topic = lambda n: set(tokens(n)) - GENERIC
    return name in ok or any(topic(name) & topic(o) for o in ok)


def evaluate(index: List[dict], fixture: dict) -> dict:
    """P@1 on positives (pick is an acceptable name), abstain-rate on negatives, false-positive rate on negatives."""
    pos, neg = fixture["positive"], fixture["negative"]
    hit = wrong = silent = 0
    misses = []
    for case in pos:
        got = pick(index, case["p"])
        if got is None:
            silent += 1; misses.append((case["p"][:50], None))
        elif same_topic(got[0].get("name") or "", case["ok"]):
            hit += 1
        else:
            wrong += 1; misses.append((case["p"][:50], got[0].get("name")))
    fp = [(p, pick(index, p)[0].get("name")) for p in neg if pick(index, p)]
    return {"p_at_1": hit / len(pos), "wrong_rate": wrong / len(pos), "abstain_rate": silent / len(pos),
            "fp_rate": len(fp) / len(neg), "fp": fp, "misses": misses}


if __name__ == "__main__":
    import json, os, sys
    idx = [json.loads(l) for l in open(os.path.expanduser("~/.agent-router/library-index.jsonl")) if l.strip()]
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "skill_select.json")))
    r = evaluate(idx, fx)
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if k not in ("fp", "misses")})
    print("wrong/silent:", r["misses"]); print("false positives:", r["fp"])
