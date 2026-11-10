# Agent Router Makefile
# Single command to run everything: backend + frontend + database

.PHONY: all help setup start stop restart test db-init lint format ui-lint clean

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UI_DIR := ui
PORT := 8080
UI_PORT := 5173

all: help

# ---- Setup ----

setup: $(VENV) ui-install ## Full setup: Python venv + npm install

$(VENV): requirements.txt
	python3.13 -m venv $(VENV)
	$(PIP) install -r requirements.txt

ui-install:
	cd $(UI_DIR) && npm install

# ---- Run ----

start: start-backend start-frontend ## Start backend + frontend together

start-backend: $(VENV) ## Start FastAPI backend on http://127.0.0.1:8080
	@echo "Starting backend on http://127.0.0.1:$(PORT)"
	$(PYTHON) main.py &
	@echo $$! > .backend.pid

start-frontend: ## Start Vite frontend on http://localhost:5173
	@echo "Starting frontend on http://localhost:$(UI_PORT)"
	cd $(UI_DIR) && npm run dev &
	@echo $$! > .frontend.pid

stop: ## Stop all running processes
	@if [ -f .backend.pid ]; then kill $$(cat .backend.pid) 2>/dev/null; rm -f .backend.pid; fi
	@if [ -f .frontend.pid ]; then kill $$(cat .frontend.pid) 2>/dev/null; rm -f .frontend.pid; fi
	@pkill -f "uvicorn main:app" 2>/dev/null || true
	@pkill -f "vite" 2>/dev/null || true
	@echo "Stopped."

restart: stop start ## Restart everything

# ---- Test ----

test: $(VENV) ## Run backend smoke tests
	$(PYTHON) -c "
import sys; sys.path.insert(0,'.')
from db.database import init_db, create_card, list_cards, get_analytics
init_db()
card_id = create_card({'title': 'Smoke test', 'lane': 'backlog', 'agent': 'test', 'model': 'test', 'status': 'triaging', 'project': None, 'prompt_sent': 'test', 'output': 'test', 'tokens_spent': 0})
cards = list_cards()
print(f'DB smoke test: OK ({len(cards)} cards, created {card_id})')
"

db-init: $(VENV) ## Initialize SQLite database
	$(PYTHON) -c "
import sys; sys.path.insert(0,'.')
from db.database import init_db
init_db()
print('Database initialized.')
"

# ---- Lint / Format ----

lint: $(VENV) ## Lint Python code
	$(PYTHON) -m ruff check . 2>/dev/null || $(PIP) install ruff && $(PYTHON) -m ruff check .

format: $(VENV) ## Format Python code
	$(PYTHON) -m ruff format . 2>/dev/null || $(PIP) install ruff && $(PYTHON) -m ruff format .

ui-lint: ## Lint frontend (if eslint configured)
	cd $(UI_DIR) && npx eslint src/ 2>/dev/null || echo "ESLint not configured, skipping"

# ---- Clean ----

clean: stop ## Remove build artifacts and venv
	rm -rf $(VENV) $(UI_DIR)/node_modules kanban.db __pycache__ .pytest_cache
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# ---- Help ----

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
