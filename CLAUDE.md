# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal AI engineering lab for learning end-to-end AI system design. The goal is to build a mini AI platform from scratch: User → App → Model → Data → Evaluation → Improvement.

## Infrastructure

- **GPU PC** (192.168.1.178): Ollama on port 11434 — serves mistral:latest, llama3:latest
- **ai-app VM** (Proxmox): Runs app services via Docker — gateway, chat UI, W&B Weave
- **ai-data VM** (Proxmox): Data services — Qdrant (planned), Postgres (planned)
- **Ceph cluster**: 4TB — RBD block storage + S3 via RadosGW

## Build & Run

```bash
# Setup
cp .env.example .env   # fill in WANDB_API_KEY

# Run full stack (from repo root)
./scripts/run_local.sh

# Run with detach
./scripts/run_local.sh -d

# Rebuild after code changes
./scripts/run_local.sh --build
```

Services start at:
- Chat UI: http://localhost:8501
- LLM Gateway: http://localhost:8000
- Gateway API docs: http://localhost:8000/docs

## Architecture

```
User → Streamlit (chat-ui:8501) → FastAPI (llm-gateway:8000) → Ollama (GPU PC:11434)
                                       ↓
                                  W&B Weave (tracing)
```

## Repository Structure

- `apps/chat-ui/` — Streamlit chat interface
- `services/llm-gateway/` — FastAPI gateway to Ollama with W&B Weave tracing
- `shared/python/ai_lab_common/` — Shared config (settings loaded from env vars)
- `infra/docker/` — Docker Compose for the full stack
- `scripts/` — Run scripts

## Key Patterns

- All config via environment variables, centralized in `shared/python/ai_lab_common/config.py`
- Dockerfiles use repo root as build context (set in docker-compose.yml)
- Gateway uses `@weave.op()` decorator on Ollama calls for automatic tracing
- Chat UI talks to gateway via internal Docker network (`http://llm-gateway:8000`)

## Tech Stack

- Python 3.12, FastAPI, Streamlit, httpx
- Ollama (local LLM inference)
- W&B Weave (tracing/observability)
- Docker Compose (deployment)
