"""LangGraph state for the agent router supervisor."""
from typing import Annotated, List, Optional, Dict, Any
from langgraph.graph import add_messages
from langchain_core.messages import BaseMessage


class RouterState(dict):
    """State shared across the LangGraph supervisor graph."""
    messages: Annotated[List[BaseMessage], add_messages]
    current_card: Optional[Dict[str, Any]] = None
    lane: Optional[str] = None
    agent: Optional[str] = None
    project: Optional[str] = None
    status: str = "triaging"  # triaging | running | review | done | blocked
    result: Optional[str] = None
    tokens_spent: int = 0
    delegation_flow: List[str] = []
    packet: Optional[Dict[str, Any]] = None
    interrupt_reason: Optional[str] = None
