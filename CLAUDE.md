# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

- **Always create a PR** for every change — never commit directly to main.
- **No Claude attribution** — no `Co-Authored-By` lines in commits, no `Generated with Claude Code` footer in PR descriptions.
- **No test plan section** in PR descriptions — just include the Summary.
- **Check PR state before pushing** — the user merges PRs quickly. Always run `gh pr view <number> --json state` before pushing follow-up commits. If already merged, create a new branch from main.
- **User merges to main** to test directly on the homelab (deploy scripts run `git pull --ff-only`).

## Project Overview

Personal AI engineering lab for learning end-to-end AI system design. The goal is to build a mini AI platform from scratch: User → App → Model → Data → Evaluation → Improvement.

## Infrastructure

- **GPU PC** (192.168.1.178, hostname: mato): Ollama on port 11434 — serves mistral:7b, qwen3.5:latest, llama3:latest. RTX 3060 12GB + GTX 1650 4GB.
- **ai-app VM** (Proxmox): Runs app services via Docker — gateway, chat UI, W&B Weave
- **ai-data VM** (192.168.1.202, Proxmox): Data services — Postgres (conversation persistence), Qdrant (vector search for RAG)
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
  ├── postgres:5432
  └── qdrant:6333
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

### Unified control (aictl.sh)

```bash
./scripts/aictl.sh start            # pull + start all services
./scripts/aictl.sh start app        # app services only
./scripts/aictl.sh restart app      # restart after deploy
./scripts/aictl.sh rebuild app      # force rebuild (no cache)
./scripts/aictl.sh status           # show all container status
./scripts/aictl.sh logs app -f      # follow app logs
./scripts/aictl.sh stop             # stop everything
```

## Architecture

```
User → Streamlit (chat-ui:8501) → FastAPI (llm-gateway:8000) → Ollama (GPU PC:11434)
                                       ↓              ↓              ↑
                                  W&B Weave      Postgres        /api/embed
                                  (tracing)      (ai-data)       (embeddings)
                                                    ↓
                                                 Qdrant
                                                (ai-data:6333)
```

### Gateway API Endpoints

**Core:**
- `GET /health` — health check (includes database + vector store status)
- `GET /models` — list available Ollama models (embedding models filtered out)
- `POST /chat` — chat completion (accepts model, message, temperature, top_p, num_predict, system_prompt, use_rag, user_id, history, conversation_id)

**Auth:**
- `GET /auth/users` — list usernames (for login dropdown, no IDs exposed)
- `POST /auth/register` — create user (username + PIN, first user is auto-admin)
- `POST /auth/login` — authenticate (returns user_id, is_admin, preferences)
- `PATCH /auth/preferences` — update user preferences (model, temperature)
- `POST /auth/change-pin` — change own PIN (requires current PIN)

**Admin (requires admin user):**
- `GET /admin/users` — list all users with IDs and admin status
- `POST /admin/reset-pin` — reset another user's PIN
- `POST /admin/toggle-admin` — grant/revoke admin
- `POST /admin/delete-user` — delete a user (conversations become unowned)

**RAG:**
- `POST /ingest` — upload a document for RAG (file upload, returns document_id + chunk count)
- `GET /documents` — list ingested documents
- `DELETE /documents/{id}` — delete a document and its vectors

**Conversations:**
- `GET /conversations` — list recent conversations (filtered by user_id query param)
- `GET /conversations/{id}` — get conversation with messages
- `DELETE /conversations/{id}` — delete a conversation

### Data Layer

Postgres stores conversations, messages, and document metadata. Qdrant stores document chunk vectors for RAG similarity search. The gateway connects to both via connection pools. If either is unreachable, the gateway degrades gracefully.

Schema is managed via numbered SQL migrations in `infra/migrations/`. The gateway runs pending migrations automatically on startup (tracked in a `_migrations` table). To add a new migration, create `infra/migrations/NNN_description.sql` (next number in sequence) — it will be applied on the next deploy. Use `IF NOT EXISTS` / `IF EXISTS` for idempotency.

Current migrations:
- `001_conversations.sql` — conversations + messages tables + pgcrypto extension
- `002_documents.sql` — documents table (RAG metadata; chunk text lives in Qdrant payloads)
- `003_users.sql` — users table (username, PIN hash, preferences) + conversations.user_id FK
- `004_user_admin.sql` — is_admin column on users
- `005_user_delete_cascade.sql` — ON DELETE SET NULL for conversations.user_id FK
- `006_user_child_flag.sql` — is_child column on users (for future guardrails)

Two compose files, one per VM:
- `infra/docker/docker-compose.yml` — ai-app VM (nginx + gateway + chat UI)
- `infra/docker/docker-compose.data.yml` — ai-data VM (Postgres + Qdrant)

### Reverse Proxy

nginx sits in front of Streamlit and the gateway on port 80. Family accesses `http://<ai-app-vm-ip>` — no port needed. Config at `infra/docker/nginx/default.conf`. The gateway API is available at `/api/` (prefix stripped).

### RAG Pipeline

Documents are ingested via `POST /ingest` (API) or `scripts/ingest.py` (CLI). The pipeline: load file → chunk (paragraph/sentence splitting with overlap) → embed via Ollama (`nomic-embed-text-v2-moe`, 768 dims) → store vectors in Qdrant with text payload.

When `use_rag=True` in a chat request, the gateway embeds the user's question, searches Qdrant for top-5 similar chunks, and injects them as context in a system prompt before calling the LLM.

The embedding model uses prefixes for optimal performance: `search_document:` for ingested chunks, `search_query:` for user questions.

### Evaluation

`scripts/eval.py` runs test cases from `datasets/eval/*.json` against the gateway's `/chat` endpoint and scores responses. Two scoring methods:

- **Keyword check**: word-boundary regex match — what fraction of expected keywords appear. Sanity baseline only.
- **LLM-as-judge**: sends the question + criteria + response to a model, asks for a 1-5 score with reason. This is the primary scoring method.

Test case format (in `datasets/eval/*.json`):
```json
{"id": "gen-001", "question": "...", "criteria": "...", "expected_keywords": ["..."]}
```

By default each model judges itself (fair comparison). Use `--judge-model` for cross-model consistency. Low temperatures: 0.3 for eval responses, 0.1 for judge scoring.

Datasets: `general.json` (8 cases), `code.json` (8 cases), `rag.json` (3 cases — auto-skipped if no documents ingested).

## Key Patterns

- **Config**: All settings via env vars, centralized in `shared/python/ai_lab_common/config.py`. A singleton `settings` object is imported everywhere. `WANDB_API_KEY` and `DATABASE_URL` should be set in `.env`.
- **Shared module imports**: In Docker, `PYTHONPATH=/app:/app/shared/python` enables `from ai_lab_common.config import settings`. For local dev, `services/llm-gateway/src/main.py` inserts the shared path into `sys.path` dynamically.
- **Docker build contexts differ**: Gateway uses repo root as context (needs `shared/` and `services/`). Chat UI uses `apps/chat-ui/` as context (self-contained, no shared module access).
- **Tracing**: Gateway uses `@weave.op()` decorator on `OllamaClient.chat()` for automatic W&B Weave tracing.
- **Chat UI → Gateway**: Uses internal Docker network hostname `http://llm-gateway:8000`, passed via `GATEWAY_URL` env var in docker-compose.
- **Graceful degradation**: Gateway starts even if Postgres, Qdrant, or Weave are unavailable — logs a warning and serves what it can.
- **Database migrations**: Numbered SQL files in `infra/migrations/` are applied automatically on gateway startup. A `_migrations` table tracks what's been applied. No manual SQL execution needed on deploy.
- **Cross-VM communication**: Services discover each other via LAN IP:port in env vars (same pattern for Ollama and Postgres).
- **Pass-through options**: The gateway validates and builds an Ollama options dict (temperature, top_p, num_predict); `OllamaClient.chat()` forwards it as-is. Adding a new Ollama option only requires a change to `ChatRequest` and the dict-building code — the client never changes.
- **PIN-based auth**: Users register with username + 4-8 digit PIN (bcrypt hashed). First registered user is auto-admin. Per-user conversations — each user sees only their own. Admin panel for user management (reset PINs, toggle admin, delete users). Settings (model, temperature) persist per-user as JSONB in the users table.
- **Smart model routing**: When "Auto" is selected (no explicit model in request), the gateway's `router.py` classifies the prompt via keyword matching and picks the best model. Code/technical prompts route to `ROUTE_CODE_MODEL` (qwen3.5), everything else to `ROUTE_DEFAULT_MODEL` (mistral). The selected model and reason are logged for observability. Users can always override by picking a specific model in the dropdown.

## Ollama Server Tuning

These environment variables are set on the GPU PC (mato) via `sudo systemctl edit ollama`:

```ini
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=16384"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KEEP_ALIVE=15m"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_NO_CLOUD=1"
```

| Variable | Value | Why |
|----------|-------|-----|
| `OLLAMA_CONTEXT_LENGTH` | `16384` | 4x default (4096). Allows longer conversations before truncation. |
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster inference + less VRAM usage on RTX 3060 (Ampere). |
| `OLLAMA_KEEP_ALIVE` | `15m` | Keeps model in VRAM 15 min after last request. Avoids reload latency between messages. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Quantizes KV cache from f16 to q8. Roughly halves context memory, enabling 16k context on 12GB. |
| `OLLAMA_NO_CLOUD` | `1` | Disables cloud/telemetry features. Fully local operation. |

## Tech Stack

- Python 3.12, FastAPI, Streamlit, httpx
- Ollama (local LLM inference + embeddings)
- Postgres 16, asyncpg (conversations, documents, users)
- Qdrant (vector search for RAG)
- bcrypt (PIN hashing)
- W&B Weave (tracing/observability)
- pypdf (PDF text extraction)
- Docker Compose (deployment)
