"""Chat API endpoint — user input → LangGraph supervisor → agent → Kanban card."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Optional, Dict, List
import sys
import os
import time
import uuid
import json

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


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoint (for Terax, Zed, and other OpenAI-client UIs)
# ---------------------------------------------------------------------------

class OpenAIMessage(BaseModel):
    role: str
    content: str


class OpenAIChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[OpenAIMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False


class OpenAIChatChoice(BaseModel):
    index: int
    message: OpenAIMessage
    finish_reason: str


class OpenAIChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[OpenAIChatChoice]
    usage: Dict[str, int] = {}


def _compose_context_message(messages: List[OpenAIMessage]) -> str:
    """Combine conversation history into a single context-aware message.

    Preserves system instructions and prior turns so the supervisor sees
    full context instead of only the last user utterance.
    """
    parts: List[str] = []
    for m in messages:
        role = m.role
        content = m.content.strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"[SYSTEM] {content}")
        elif role == "user":
            parts.append(f"[USER] {content}")
        elif role == "assistant":
            parts.append(f"[ASSISTANT] {content}")
        elif role == "tool":
            parts.append(f"[TOOL RESULT] {content}")
    return "\n\n".join(parts)


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.post("/v1/chat/completions", response_model=OpenAIChatResponse)
async def openai_chat_completions(request: OpenAIChatRequest):
    """OpenAI-compatible chat completions endpoint.

    Accepts standard OpenAI ChatCompletionRequest format, preserves the full
    conversation history (system + prior turns), routes it through the agent
    router (research-enforcement, triage, dispatch, evaluate), and returns an
    OpenAI-compatible response.

    This lets Terax, Zed, and any OpenAI-client UI use the agent-router as
    their default model provider with research-enforcement and proper
    skill/agent/model selection.
    """
    if supervisor is None:
        raise HTTPException(status_code=500, detail="Supervisor not initialized")

    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages found")

    # Last user message is the current input
    user_messages = [m for m in request.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message found")
    user_message = user_messages[-1].content

    # Compose full conversation context for the supervisor
    context_message = _compose_context_message(request.messages)

    # Determine model: use requested model or default to NIM_1 Super VL
    model = request.model or "nim-nemotron-3-5-super-vl-1"

    # Handle streaming (SSE)
    if request.stream:
        async def event_stream():
            yield _sse_event({
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            })
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        result = supervisor.run(
            context_message,
            model=model,
        )

        if result.get("status") == "blocked":
            reason = result.get("interrupt_reason", "blocked")
            content = f"[agent-router blocked] {reason}"
            return OpenAIChatResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
                created=int(time.time()),
                model=model,
                choices=[
                    OpenAIChatChoice(
                        index=0,
                        message=OpenAIMessage(role="assistant", content=content),
                        finish_reason="stop",
                    )
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

        content = result.get("result", "") or ""
        if result.get("interrupt_reason"):
            content = f"[{result['interrupt_reason']}]\n{content}"

        # Append routing info for transparency
        route_info = f"\n\n---\nRouter: lane={result.get('lane')}, agent={result.get('agent')}, model={result.get('chosen_model')}"
        if result.get("delegation_flow"):
            route_info += f"\nFlow: {' -> '.join(result['delegation_flow'])}"

        return OpenAIChatResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=model,
            choices=[
                OpenAIChatChoice(
                    index=0,
                    message=OpenAIMessage(role="assistant", content=content + route_info),
                    finish_reason="stop",
                )
            ],
            usage={
                "prompt_tokens": len(context_message.split()),
                "completion_tokens": len(content.split()),
                "total_tokens": len(context_message.split()) + len(content.split()),
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
