"""Prompt library benchmarking & agent response quality evaluation.

Uses NIM 3 as LLM judge to score completed cards on PEEM criteria:
  Accuracy, Coherence, Relevance, Objectivity, Clarity, Conciseness.

Stores scores in SQLite for analytics and continuous quality feedback.
"""
import os
import json
import sys
from typing import Dict, Any, Optional, List
from pathlib import Path

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, "Developer", "agent-router", "config")

sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
from db.database import get_connection, add_token_usage, update_card

PEEM_CRITERIA = [
    "accuracy",      # Is the information correct?
    "coherence",     # Does it flow logically?
    "relevance",     # Does it answer the question asked?
    "objectivity",   # Is it unbiased and factual?
    "clarity",       # Is it clear and understandable?
    "conciseness",   # Is it concise without fluff?
]

JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of agent responses. Score the following agent output on PEEM criteria (1-5 each):

1. Accuracy - Is the information correct and factually grounded?
2. Coherence - Does the response flow logically and stay on topic?
3. Relevance - Does it directly answer the user's request?
4. Objectivity - Is it unbiased, not manufactured?
5. Clarity - Is it clear, well-structured, easy to understand?
6. Conciseness - Is it concise, without filler or verbosity?

Also provide:
- overall_score (1-5, average of the 6)
- strengths (brief list)
- weaknesses (brief list)
- improvement (single highest-leverage fix)
- verdict: one of "PASS", "PASS_WITH_NOTES", "FAIL"

Respond ONLY with valid JSON. No markdown, no explanations outside JSON.
"""


def load_llm_judge():
    """Initialize NIM 3 as the LLM judge."""
    from langchain_nvidia_ai_endpoints import ChatNVIDIA
    api_key = os.environ.get("NIM_3", "")
    if not api_key:
        return None
    return ChatNVIDIA(
        model="nvidia/nemotron-3.5-super-vl-120b-a12b",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key,
        temperature=0.1,
        max_tokens=2048,
    )


def evaluate_card(card: dict, judge_llm=None) -> dict:
    """Evaluate a completed card using LLM-as-judge on PEEM criteria."""
    prompt_sent = card.get("prompt_sent", "") or ""
    output = card.get("output", "") or ""
    agent = card.get("agent", "unknown")
    model = card.get("model", "unknown")

    if judge_llm is None:
        judge_llm = load_llm_judge()

    if judge_llm is None:
        return {
            "card_id": card["id"],
            "error": "NIM_3 API key not set — cannot evaluate",
            "status": "skipped",
        }

    eval_prompt = f"""Evaluate this agent response:

USER REQUEST (prompt sent to agent):
{prompt_sent[:2000]}

AGENT OUTPUT:
{output[:4000]}

Score on PEEM criteria (1-5 each). Return JSON only."""

    try:
        response = judge_llm.invoke(eval_prompt)
        content = response.content if hasattr(response, "content") else str(response)
        # Try to parse JSON from response
        try:
            scores = json.loads(content)
        except json.JSONDecodeError:
            # Extract JSON from markdown code blocks if present
            import re
            m = re.search(r"```json\n(.*?)\n```", content, re.S)
            if m:
                scores = json.loads(m.group(1))
            else:
                scores = {"raw": content, "parse_error": True}

        # Normalize scores to 1-5
        normalized = {}
        for crit in PEEM_CRITERIA:
            val = scores.get(crit, 3)
            try:
                normalized[crit] = max(1, min(5, int(val)))
            except (ValueError, TypeError):
                normalized[crit] = 3

        overall = sum(normalized.values()) / len(normalized)
        verdict = "PASS" if overall >= 4.0 else ("PASS_WITH_NOTES" if overall >= 3.0 else "FAIL")

        result = {
            "card_id": card["id"],
            "agent": agent,
            "model": model,
            "peem_scores": normalized,
            "overall_score": round(overall, 2),
            "verdict": verdict,
            "strengths": scores.get("strengths", []),
            "weaknesses": scores.get("weaknesses", []),
            "improvement": scores.get("improvement", ""),
            "status": "evaluated",
        }
        return result
    except Exception as e:
        return {
            "card_id": card["id"],
            "error": str(e),
            "status": "error",
        }


def evaluate_all_pending(judge_llm=None) -> List[dict]:
    """Evaluate all cards that haven't been evaluated yet."""
    from db.database import list_cards

    cards = list_cards(status="done")
    results = []
    for card in cards:
        # Check if already evaluated (could add evals table later)
        result = evaluate_card(card, judge_llm)
        results.append(result)
    return results


def store_evaluation(card_id: str, evaluation: dict) -> None:
    """Store evaluation results. For now, we could add an evals table or append to card metadata."""
    conn = get_connection()
    # Create evals table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id TEXT NOT NULL,
            agent TEXT,
            model TEXT,
            accuracy INTEGER,
            coherence INTEGER,
            relevance INTEGER,
            objectivity INTEGER,
            clarity INTEGER,
            conciseness INTEGER,
            overall_score REAL,
            verdict TEXT,
            strengths TEXT,
            weaknesses TEXT,
            improvement TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (card_id) REFERENCES cards(id)
        )
    """)
    peem = evaluation.get("peem_scores", {})
    conn.execute("""
        INSERT INTO evaluations (card_id, agent, model, accuracy, coherence, relevance, objectivity, clarity, conciseness, overall_score, verdict, strengths, weaknesses, improvement, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        card_id,
        evaluation.get("agent"),
        evaluation.get("model"),
        peem.get("accuracy"),
        peem.get("coherence"),
        peem.get("relevance"),
        peem.get("objectivity"),
        peem.get("clarity"),
        peem.get("conciseness"),
        evaluation.get("overall_score"),
        evaluation.get("verdict"),
        json.dumps(evaluation.get("strengths", [])),
        json.dumps(evaluation.get("weaknesses", [])),
        evaluation.get("improvement"),
        evaluation.get("status"),
    ))
    conn.commit()
    conn.close()


def get_evaluation_analytics() -> dict:
    """Get evaluation analytics: average scores per agent, per criterion, verdict distribution."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT agent, model, AVG(overall_score) as avg_score,
                   AVG(accuracy) as avg_accuracy, AVG(coherence) as avg_coherence,
                   AVG(relevance) as avg_relevance, AVG(objectivity) as avg_objectivity,
                   AVG(clarity) as avg_clarity, AVG(conciseness) as avg_conciseness,
                   COUNT(*) as eval_count,
                   SUM(CASE WHEN verdict = 'PASS' THEN 1 ELSE 0 END) as pass_count,
                   SUM(CASE WHEN verdict = 'FAIL' THEN 1 ELSE 0 END) as fail_count
            FROM evaluations
            GROUP BY agent, model
        """).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
