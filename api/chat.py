"""Chat API endpoint — user input → LangGraph supervisor → agent → Kanban card."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from graph.supervisor import RouterSupervisor

router = APIRouter()

# Single supervisor instance (MVP)
supervisor = RouterSupervisor()


class ChatRequest(BaseModel):
    message: str
    project: Optional[str] = None


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


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a message to the agent router."""
    try:
        result = supervisor.run(request.message, project=request.project)
        return ChatResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/approve")
async def approve_gate(request: ChatRequest):
    """Approve a gated action and resume."""
    # Resume the interrupted graph
    result = supervisor.run(request.message, project=request.project)
    return ChatResponse(**result)
