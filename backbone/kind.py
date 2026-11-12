"""Nearest-example text classifier: label a query by cosine-voting over labeled examples, where example and query vectors are weighted by inverse document frequency so rare tokens dominate the similarity score."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import List, Tuple


def tokenize(text: str) -> List[str]:
    """Lowercase word tokens of length at least two."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 2]


def predict_kind(query: str, examples: List[Tuple[str, str]], k: int = 5) -> Tuple[str, float]:
    """Return (kind, margin) for query voted on by the top k matching examples."""
    if not examples:
        return ("", 0.0)

    n = len(examples)
    doc_freq: dict[str, int] = defaultdict(int)
    example_tokens: List[set[str]] = []
    for text, _ in examples:
        tokens = set(tokenize(text))
        example_tokens.append(tokens)
        for token in tokens:
            doc_freq[token] += 1

    def idf(token: str) -> float:
        return math.log(n / doc_freq[token])

    def vector(tokens: set[str]) -> dict[str, float]:
        return {token: idf(token) for token in tokens if token in doc_freq}

    example_vecs = [vector(ts) for ts in example_tokens]
    example_norms = [
        math.sqrt(sum(w * w for w in vec.values())) for vec in example_vecs
    ]

    query_vec = vector(set(tokenize(query)))
    query_norm = math.sqrt(sum(w * w for w in query_vec.values()))

    candidates: List[Tuple[float, int]] = []
    for idx, (evec, norm) in enumerate(zip(example_vecs, example_norms)):
        if query_norm == 0.0 or norm == 0.0:
            continue
        dot = sum(query_vec.get(t, 0.0) * w for t, w in evec.items())
        sim = dot / (query_norm * norm)
        if sim > 0.0:
            candidates.append((sim, idx))

    if not candidates:
        return ("", 0.0)

    candidates.sort(key=lambda item: item[0], reverse=True)
    top_k = candidates[:k]

    kind_votes: dict[str, float] = defaultdict(float)
    for sim, idx in top_k:
        kind_votes[examples[idx][1]] += sim

    best_kind = ""
    best_vote = -1.0
    for text, kind in examples:  # earliest example order wins ties
        vote = kind_votes.get(kind, 0.0)
        if vote > best_vote:
            best_vote = vote
            best_kind = kind

    sims = [sim for sim, _ in top_k]
    total = sum(sims)
    top_vote = sims[0]
    second_vote = sims[1] if len(sims) > 1 else 0.0
    margin = (top_vote - second_vote) / total if total > 0 else 0.0
    margin = min(1.0, max(0.0, margin))

    return (best_kind, margin)
