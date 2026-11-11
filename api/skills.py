"""Skills and RAG retrieval API endpoints.

- GET /api/skills — list all indexed skills with descriptions
- GET /api/retrieve — RAG retrieval: ?q=<query> → relevant skills/hooks/vault context
"""
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List, Optional
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

router = APIRouter()


@router.get("/skills")
async def list_skills():
    """List all indexed skills from skills.yaml (skills.yaml + ECC + agency)."""
    import yaml as _yaml
    path = os.path.join(HOME, "Developer", "agent-router", "config", "skills.yaml")
    try:
        with open(path) as f:
            cfg = _yaml.safe_load(f) or {}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="skills.yaml not found")

    skills = []
    for s in cfg.get("skills", []):
        skills.append({
            "id": s.get("id", ""),
            "category": s.get("category", ""),
            "description": s.get("description", ""),
            "path": s.get("path", ""),
        })
    return {"skills": skills, "count": len(skills)}


@router.get("/retrieve")
async def retrieve(q: str, top_k: int = 8):
    """RAG retrieval: query the local index for relevant skills/hooks/systems/vault.

    Uses the same index as the supervisor's index_retrieval_node.
    """
    if not q:
        raise HTTPException(status_code=400, detail="q parameter required")

    sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router", "scripts"))
    try:
        from index_vault import search
        results = search(q, top_k=top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Index search failed: {e}")

    return {
        "query": q,
        "results": results,
        "count": len(results),
    }
