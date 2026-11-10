"""Analytics API endpoints."""
from fastapi import APIRouter
from typing import Dict, Any
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from db import get_analytics

router = APIRouter()


@router.get("/analytics", response_model=Dict[str, Any])
async def get_analytics_endpoint():
    return get_analytics()
