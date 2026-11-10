"""FastAPI application entry point for the Agent Router."""
import os
import sys
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

HOME = os.path.expanduser("~")
sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))

from api.chat import router as chat_router
from api.cards import router as cards_router
from api.analytics import router as analytics_router
from api.projects import router as projects_router
from api.evaluate import router as evaluate_router

app = FastAPI(
    title="Agent Router",
    description="LangGraph-based multi-agent router with Kanban UI",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(cards_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(evaluate_router, prefix="/api")


@app.get("/")
async def root():
    return {"name": "Agent Router", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="127.0.0.1", port=port)
