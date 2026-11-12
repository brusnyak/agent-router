"""Model reasoning for retrieval: (1) expand the raw request into what a matching library entry would be called,
(2) rerank candidates by reasoning over their descriptions. Both are NIM calls; failures fall back to the input."""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List

Chat = Callable[[List[dict]], str]


def expand(chat: Chat, query: str, kinds: str = "skills, agent personas, commands, playbooks") -> str:
    p = (f"A user request will be served by an entry from a library of {kinds}. Think about the real GOAL behind the request, "
         "then write ONE line: likely entry names (kebab-case, 3 guesses), the role or task class, and 8 keywords such an entry "
         f"would contain. No prose.\n\nRequest: {query[:600]}")
    try:
        return chat([{"role": "user", "content": p}]).strip().splitlines()[-1][:400]
    except Exception:
        return ""


def rerank(chat: Chat, query: str, cands: List[Dict], k: int = 3) -> List[Dict]:
    """Show 10 candidates with real descriptions; the model reasons briefly and returns its best names in order."""
    cands = cands[:10]
    lines = "\n".join(f"{i + 1}. {c['name']}: {(c.get('description') or '')[:170]}" for i, c in enumerate(cands))
    p = (f"Request: {query[:500]}\n\nCandidates:\n{lines}\n\nPick the {k} entries that best DO the job the request needs "
         "(a specific entry beats a generic one; wrong language/tool is a miss). Reason in two sentences, then a last line "
         'exactly like: {"best": ["name1","name2","name3"]}')
    try:
        raw = chat([{"role": "user", "content": p}])
        m = re.findall(r"\{[^{}]*\"best\"[^{}]*\}", raw, re.S)
        names = json.loads(m[-1])["best"]
        by = {c["name"]: c for c in cands}
        out = [by[n] for n in names if n in by]
        return out + [c for c in cands if c not in out]
    except Exception:
        return cands
