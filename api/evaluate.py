"""Evaluation / benchmarking API endpoints."""
from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from graph.evaluation import (
    evaluate_card, evaluate_all_pending, store_evaluation,
    get_evaluation_analytics, PEEM_CRITERIA, load_llm_judge,
)

router = APIRouter()


@router.post("/evaluate/{card_id}")
async def evaluate_card_endpoint(card_id: str):
    """Evaluate a single completed card using NIM 3 LLM judge (PEEM criteria)."""
    from db.database import get_card

    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    judge_llm = load_llm_judge()
    if judge_llm is None:
        raise HTTPException(
            status_code=400,
            detail="NIM_3 API key not set. Set NIM_3 env var to enable evaluation.",
        )

    result = evaluate_card(card, judge_llm)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error"))

    store_evaluation(card_id, result)
    return result


@router.post("/evaluate/all")
async def evaluate_all_endpoint():
    """Evaluate all pending (done, not yet evaluated) cards."""
    judge_llm = load_llm_judge()
    if judge_llm is None:
        raise HTTPException(
            status_code=400,
            detail="NIM_3 API key not set. Set NIM_3 env var to enable evaluation.",
        )

    results = evaluate_all_pending(judge_llm)
    for r in results:
        if r.get("status") == "evaluated":
            store_evaluation(r["card_id"], r)

    return {"evaluated": len(results), "results": results}


@router.get("/evaluate/analytics")
async def evaluation_analytics_endpoint() -> List[Dict[str, Any]]:
    """Get evaluation analytics: average PEEM scores per agent/model."""
    return get_evaluation_analytics()


@router.get("/evaluate/criteria")
async def evaluation_criteria_endpoint():
    """Return the PEEM evaluation criteria."""
    return {"criteria": PEEM_CRITERIA}
