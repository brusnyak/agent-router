"""Kanban card API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import os

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from db import (
    create_card, get_card, list_cards, update_card,
    add_comment, get_comments,
)

router = APIRouter()


class CardCreate(BaseModel):
    title: str
    lane: str = "backlog"
    agent: str
    model: str
    status: str = "triaging"
    project: Optional[str] = None
    prompt_sent: Optional[str] = None
    output: Optional[str] = None
    tokens_spent: int = 0


class CardUpdate(BaseModel):
    title: Optional[str] = None
    lane: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    status: Optional[str] = None
    project: Optional[str] = None
    prompt_sent: Optional[str] = None
    output: Optional[str] = None
    tokens_spent: Optional[int] = None


class CommentCreate(BaseModel):
    card_id: str
    author: str
    body: str


@router.post("/cards")
async def create_card_endpoint(card: CardCreate):
    card_id = create_card(card.model_dump())
    return {"id": card_id, **card.model_dump()}


@router.get("/cards")
async def list_cards_endpoint(status: Optional[str] = None, lane: Optional[str] = None):
    cards = list_cards(status=status, lane=lane)
    return {"cards": cards}


@router.get("/cards/{card_id}")
async def get_card_endpoint(card_id: str):
    card = get_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    comments = get_comments(card_id)
    card["comments"] = comments
    return card


@router.patch("/cards/{card_id}")
async def update_card_endpoint(card_id: str, updates: CardUpdate):
    update_data = {k: v for k, v in updates.model_dump().items() if v is not None}
    success = update_card(card_id, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Card not found or no changes")
    return {"success": True}


@router.post("/comments")
async def add_comment_endpoint(comment: CommentCreate):
    comment_id = add_comment(comment.card_id, comment.author, comment.body)
    return {"id": comment_id, **comment.model_dump()}
