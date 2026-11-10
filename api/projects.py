"""Project API endpoints."""
from fastapi import APIRouter
from typing import List, Dict, Any
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from langgraph.tools import discover_projects

router = APIRouter()


@router.get("/projects", response_model=List[Dict[str, Any]])
async def list_projects_endpoint():
    return discover_projects()
