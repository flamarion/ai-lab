# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal AI engineering lab for learning end-to-end AI system design. The goal is to build a mini AI platform from scratch: User → App → Model → Data → Evaluation → Improvement.

## Infrastructure

- **GPU PC** (192.168.1.178): Ollama on port 11434 — serves mistral:latest, llama3:latest
- **ai-app VM** (Proxmox): Runs app services via Docker — gateway, chat UI, W&B Weave
- **ai-data VM** (192.168.1.202, Proxmox): Data services — Postgres (conversation persistence)
- **Ceph cluster**: 4TB — RBD block storage + S3 via RadosGW

### Network topology
```
ai-app VM (Proxmox)  ---- LAN ---->  GPU PC (192.168.1.178)
  ├── chat-ui:8501                     └── Ollama:11434
  └── llm-gateway:8000
         |
         LAN
         v
ai-data VM (Proxmox)
  └── postgres:5432
```

## Build & Run

```bash
# Setup
cp .env.example .env   # fill in WANDB_API_KEY and DATABASE_URL

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

### ai-app VM (gateway + chat UI)

```bash
# First-time setup on the VM:
git clone <repo-url> ~/ai-lab && cd ~/ai-lab
cp .env.example .env   # fill in WANDB_API_KEY and DATABASE_URL

# Deploy (pulls latest, builds, starts detached)
./scripts/deploy-app.sh

# Management
./scripts/deploy-app.sh --status   # container status
./scripts/deploy-app.sh --logs     # view logs (add -f to follow)
./scripts/deploy-app.sh --down     # stop everything
```

### ai-data VM (Postgres)

```bash
# First-time setup on the VM:
git clone <repo-url> ~/ai-lab && cd ~/ai-lab
cp .env.example .env   # set POSTGRES_PASSWORD

# Deploy
./scripts/deploy-data.sh

# Management
./scripts/deploy-data.sh --status
./scripts/deploy-data.sh --logs
./scripts/deploy-data.sh --down
```

Services are accessible from any LAN device at `http://<ai-app-vm-ip>:8501` (Chat UI) and `http://<ai-app-vm-ip>:8000` (Gateway).

**How it works:** Deploy scripts run `git pull --ff-only` then `docker compose up --build -d`. Containers run detached so they survive SSH disconnect. `restart: unless-stopped` in the compose files handles VM reboots — no systemd needed.

## Architecture

```
User → Streamlit (chat-ui:8501) → FastAPI (llm-gateway:8000) → Ollama (GPU PC:11434)
                                       ↓              ↓
                                  W&B Weave      Postgres (ai-data VM:5432)
                                  (tracing)      (conversations)
```

### Gateway API Endpoints

- `GET /health` — health check (includes database status)
- `GET /models` — list available Ollama models
- `POST /chat` — chat completion (accepts model, message, temperature, history, conversation_id)
- `GET /conversations` — list recent conversations
- `GET /conversations/{id}` — get conversation with messages
- `DELETE /conversations/{id}` — delete a conversation

### Data Layer

Postgres stores conversations and messages. The gateway connects via `asyncpg` with a connection pool. If Postgres is unreachable, the gateway degrades gracefully — chat still works but without persistence.

Schema is initialized via `infra/docker/init-db/001_schema.sql` (mounted into `/docker-entrypoint-initdb.d/`).

Two compose files, one per VM:
- `infra/docker/docker-compose.yml` — ai-app VM (gateway + chat UI)
- `infra/docker/docker-compose.data.yml` — ai-data VM (Postgres)

## Key Patterns

- **Config**: All settings via env vars, centralized in `shared/python/ai_lab_common/config.py`. A singleton `settings` object is imported everywhere. `WANDB_API_KEY` and `DATABASE_URL` should be set in `.env`.
- **Shared module imports**: In Docker, `PYTHONPATH=/app:/app/shared/python` enables `from ai_lab_common.config import settings`. For local dev, `services/llm-gateway/src/main.py` inserts the shared path into `sys.path` dynamically.
- **Docker build contexts differ**: Gateway uses repo root as context (needs `shared/` and `services/`). Chat UI uses `apps/chat-ui/` as context (self-contained, no shared module access).
- **Tracing**: Gateway uses `@weave.op()` decorator on `OllamaClient.chat()` for automatic W&B Weave tracing.
- **Chat UI → Gateway**: Uses internal Docker network hostname `http://llm-gateway:8000`, passed via `GATEWAY_URL` env var in docker-compose.
- **Graceful degradation**: Gateway starts even if Postgres or Weave are unavailable — logs a warning and serves stateless requests.
- **Cross-VM communication**: Services discover each other via LAN IP:port in env vars (same pattern for Ollama and Postgres).

## Tech Stack

- Python 3.12, FastAPI, Streamlit, httpx
- Ollama (local LLM inference)
- Postgres 16, asyncpg (conversation persistence)
- W&B Weave (tracing/observability)
- Docker Compose (deployment)
