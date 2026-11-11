"""Chat API endpoint — user input → LangGraph supervisor → agent → Kanban card."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional, Dict, List
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

router = APIRouter()

# Supervisor is injected from main.py
supervisor: Any = None


def set_supervisor(sup: Any):
    global supervisor
    supervisor = sup


class ChatRequest(BaseModel):
    message: str
    project: Optional[str] = None
    lane: Optional[str] = None
    model: Optional[str] = None
    skills: Optional[List[str]] = None


class ChatResponse(BaseModel):
    status: str
    lane: Optional[str] = None
    agent: Optional[str] = None
    project: Optional[str] = None
    result: Optional[str] = None
    card: Optional[Dict[str, Any]] = None
    tokens_spent: int = 0
    delegation_flow: list[str] = []
    interrupt_reason: Optional[str] = None
    index_context: Optional[str] = None
    chosen_model: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the agent router with explicit dispatch overrides."""
    if supervisor is None:
        raise HTTPException(status_code=500, detail="Supervisor not initialized")
    try:
        result = supervisor.run(
            request.message,
            project=request.project,
            lane=request.lane,
            model=request.model,
            skills=request.skills,
        )
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/approve")
async def approve_gate(request: ChatRequest):
    """Approve a gated action and resume."""
    if supervisor is None:
        raise HTTPException(status_code=500, detail="Supervisor not initialized")
    result = supervisor.run(request.message, project=request.project)
    return ChatResponse(**result)
