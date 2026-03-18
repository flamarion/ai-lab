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

**No test suite, linter, or CI pipeline exists yet.** Dependencies are pinned in per-service `requirements.txt` files (no lock files).

## Homelab Deployment

The stack runs on the **ai-app VM** (Proxmox), talking to Ollama on the GPU PC over the LAN.

```bash
# First-time setup on the VM:
git clone <repo-url> ~/ai-lab && cd ~/ai-lab
cp .env.example .env   # fill in WANDB_API_KEY

# Deploy (pulls latest, builds, starts detached)
./scripts/deploy-app.sh

# Management
./scripts/deploy-app.sh --status   # container status
./scripts/deploy-app.sh --logs     # view logs (add -f to follow)
./scripts/deploy-app.sh --down     # stop everything
```

Services are accessible from any LAN device at `http://<ai-app-vm-ip>:8501` (Chat UI) and `http://<ai-app-vm-ip>:8000` (Gateway).

**How it works:** `deploy-app.sh` runs `git pull --ff-only` then `docker compose up --build -d`. Containers run detached so they survive SSH disconnect. `restart: unless-stopped` in the compose file handles VM reboots — no systemd needed.

## Architecture

```
User → Streamlit (chat-ui:8501) → FastAPI (llm-gateway:8000) → Ollama (GPU PC:11434)
                                       ↓
                                  W&B Weave (tracing)
```

### Gateway API Endpoints

- `GET /health` — health check
- `GET /models` — list available Ollama models
- `POST /chat` — chat completion (accepts model, message, temperature, history)

## Key Patterns

- **Config**: All settings via env vars, centralized in `shared/python/ai_lab_common/config.py`. A singleton `settings` object is imported everywhere. Only `WANDB_API_KEY` has no default and must be set in `.env`.
- **Shared module imports**: In Docker, `PYTHONPATH=/app:/app/shared/python` enables `from ai_lab_common.config import settings`. For local dev, `services/llm-gateway/src/main.py` inserts the shared path into `sys.path` dynamically.
- **Docker build contexts differ**: Gateway uses repo root as context (needs `shared/` and `services/`). Chat UI uses `apps/chat-ui/` as context (self-contained, no shared module access).
- **Tracing**: Gateway uses `@weave.op()` decorator on `OllamaClient.chat()` for automatic W&B Weave tracing.
- **Chat UI → Gateway**: Uses internal Docker network hostname `http://llm-gateway:8000`, passed via `GATEWAY_URL` env var in docker-compose.

## Tech Stack

- Python 3.12, FastAPI, Streamlit, httpx
- Ollama (local LLM inference)
- W&B Weave (tracing/observability)
- Docker Compose (deployment)
