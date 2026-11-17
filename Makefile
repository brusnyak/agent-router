# agent-router — one-command entry point.
# Replaces the quickstart shell block. Secrets (NIM keys) are read from the
# environment via ~/.claude/scripts/with-env; values are never printed or stored.
# Default target: show help.

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
BACKBONE := $(BIN)/python -m backbone
WITH_ENV := ~/.claude/scripts/with-env

.PHONY: help setup install doctor discover init keys run ask enrich test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

setup: ## Create venv and install dependencies
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt

install: setup ## Alias for setup (one-command install)

doctor: ## Probe every detected worker (read-only)
	$(BACKBONE) doctor

discover: ## Detect agents, keys, ssh hosts, projects on this machine
	$(BACKBONE) discover

init: ## Write ~/.agent-router/backbone.yaml from discovery
	$(BACKBONE) init

keys: ## Show NIM key status (values never printed)
	$(WITH_ENV) NIM_1 NIM_2 NIM_3 -- $(BACKBONE) keys

run: ## Run one task: make run prompt="..." [worker=nim1] [gate="..."]
	$(WITH_ENV) NIM_1 NIM_2 NIM_3 -- $(BACKBONE) run $(worker) --gate "$(gate)" "$(prompt)"

ask: ## Free text: NIM1 plans, router runs, critic reviews: make ask text="..."
	$(WITH_ENV) NIM_1 NIM_2 NIM_3 -- $(BACKBONE) ask --dry "$(text)"

compile: ## Dictation to a compact card: make compile text="..."
	$(BACKBONE) compile --no-llm "$(text)"

enrich: ## Fill would_surface on receipts (NIM embeddings)
	$(WITH_ENV) NIM_1 NIM_2 NIM_3 -- $(BACKBONE) enrich

test: ## Run the test suite
	$(BIN)/python -m pytest tests -q

clean: ## Remove venv and generated data
	rm -rf $(VENV) data
