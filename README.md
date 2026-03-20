# AI Lab

Personal AI engineering lab for learning end-to-end AI system design. The goal is to build a mini AI platform from scratch — User → App → Model → Data → Evaluation → Improvement — running entirely on homelab infrastructure.

This is not about playing with models. It's about learning how **real AI systems work in production**: inference, applications, knowledge retrieval, agents, evaluation, and improvement.

## What's Built

- **Chat UI** (Streamlit) — multi-page app with Chat, Settings, and Admin pages
- **LLM Gateway** (FastAPI) — abstracts Ollama, handles auth, RAG, smart routing, conversations
- **RAG pipeline** — ingest documents (PDF, DOCX, XLSX, text, code, config), chunk, embed, vector search via Qdrant
- **Smart model routing** — code prompts route to qwen3.5, general prompts to mistral:7b (override anytime)
- **PIN-based auth** — per-user conversations, first user is auto-admin, child account flag
- **Admin panel** — manage users, toggle admin/child, reset PINs, delete users
- **Multi-file upload** — 40+ file types supported in chat and settings
- **Settings persistence** — per-user model/temperature preferences stored in Postgres
- **Observability** — W&B Weave tracing (optional, toggle via env var)
- **nginx reverse proxy** — family accesses `http://<vm-ip>` on port 80, no port needed
- **Auto migrations** — numbered SQL files applied on gateway startup, advisory-locked

## Architecture

```
User → nginx (:80) → Streamlit (chat-ui:8501) → FastAPI (llm-gateway:8000) → Ollama (GPU PC:11434)
                                                      ↓              ↓              ↑
                                                 W&B Weave      Postgres        /api/embed
                                                 (tracing)      (ai-data)       (embeddings)
                                                                   ↓
                                                                Qdrant
                                                               (ai-data:6333)
```

### Infrastructure

| Host | Role | Details |
|------|------|---------|
| **GPU PC** (mato, 192.168.1.178) | Inference | Ollama :11434 — mistral:7b, qwen3.5, llama3, nomic-embed-text-v2-moe. RTX 3060 12GB + GTX 1650 4GB |
| **ai-app VM** (Proxmox) | Application | nginx + gateway + chat UI via Docker |
| **ai-data VM** (192.168.1.202, Proxmox) | Data | Postgres :5432 + Qdrant :6333 via Docker |
| **Ceph cluster** | Storage | 4TB — RBD block + S3 via RadosGW (available, not yet used) |

## Quick Start

```bash
# Setup
cp .env.example .env   # fill in WANDB_API_KEY and DATABASE_URL

# Run full stack locally
./scripts/run_local.sh

# Run detached
./scripts/run_local.sh -d

# Rebuild after code changes
./scripts/run_local.sh --build
```

Services start at:
- Chat UI: http://localhost:8501
- LLM Gateway: http://localhost:8000
- Gateway API docs: http://localhost:8000/docs

## Homelab Deployment

```bash
# ai-app VM (gateway + chat UI)
./scripts/deploy-app.sh              # pull + build + start detached
./scripts/deploy-app.sh --status     # container status
./scripts/deploy-app.sh --logs       # view logs (add -f to follow)
./scripts/deploy-app.sh --down       # stop everything

# ai-data VM (Postgres + Qdrant)
./scripts/deploy-data.sh             # same flags as above

# Unified control
./scripts/aictl.sh start             # pull + start all services
./scripts/aictl.sh start app         # app services only
./scripts/aictl.sh rebuild app       # force rebuild (no cache)
./scripts/aictl.sh status            # show all container status
./scripts/aictl.sh logs app -f       # follow app logs
./scripts/aictl.sh stop              # stop everything
```

Deploy scripts run `git pull --ff-only` then `docker compose up --build -d`. Containers run detached and use `restart: unless-stopped` to survive reboots.

## Evaluation

Run test cases against your models through the gateway, score responses with LLM-as-judge, and compare models side by side.

```bash
# Compare all available models on general + code datasets
python scripts/eval.py --gateway http://localhost/api

# Test specific models
python scripts/eval.py --models mistral:7b,qwen3.5:latest --gateway http://localhost/api

# Run only code tests
python scripts/eval.py --categories code --gateway http://localhost/api

# Include RAG tests (requires ingested documents)
python scripts/eval.py --categories general,code,rag --gateway http://localhost/api

# Use a consistent judge model across all evaluations
python scripts/eval.py --judge-model mistral:7b --gateway http://localhost/api

# Save results to JSON for tracking over time
python scripts/eval.py -o results.json --gateway http://localhost/api
```

The gateway runs behind nginx at `/api` — use `http://localhost/api` (or `http://<ai-app-vm-ip>/api` from another machine).

The runner scores each response two ways:
- **Keyword check** — do expected terms appear in the response? (sanity baseline)
- **LLM-as-judge** — a model rates the response 1-5 against grading criteria (the real score)

Output includes a comparison table with averages by model, by category, and flags cases where models disagree by 2+ points.

Test cases live in `datasets/eval/*.json` — add your own by following the same format (question, criteria, expected keywords).

### Weave Evaluation (tracked)

For tracked evaluations with the W&B Weave dashboard — versioned datasets, model configs, scorer results, and run-over-run comparison:

```bash
# Prerequisites: pip install weave wandb httpx
# Requires WANDB_API_KEY set in your environment

python scripts/eval_weave.py

# Specific model with a consistent judge
python scripts/eval_weave.py --models mistral:7b --judge-model mistral:7b
```

Results appear in the Weave dashboard where you can compare runs, inspect per-prediction scores, and track quality over time.

## Repository Layout

```
ai-lab/
├── README.md
├── CLAUDE.md                          # Claude Code project instructions
├── ROADMAP.md                         # Learning phases and progress
├── LICENSE
├── .env.example
├── datasets/
│   └── eval/
│       ├── general.json               # General knowledge test cases (8)
│       ├── code.json                  # Code/technical test cases (8)
│       └── rag.json                   # RAG-dependent test cases (3)
├── apps/
│   └── chat-ui/
│       ├── app.py                     # Streamlit multi-page app (chat, settings, admin)
│       ├── Dockerfile
│       └── requirements.txt
├── services/
│   └── llm-gateway/
│       ├── src/
│       │   ├── main.py                # FastAPI app (chat, auth, admin, RAG, conversations)
│       │   ├── ollama_client.py       # Ollama HTTP client (chat + embed)
│       │   ├── router.py              # Smart model routing (code vs general)
│       │   ├── db.py                  # asyncpg connection pool and queries
│       │   ├── chunker.py             # Document loading and chunking
│       │   ├── vector_store.py        # Qdrant wrapper (upsert, search, delete)
│       │   ├── migrations.py          # Auto-apply SQL migrations on startup
│       │   └── mcp_client.py          # MCP client manager (connect to MCP servers)
│       ├── mcp_servers.json           # MCP server config (same format as Claude Desktop)
│       ├── Dockerfile
│       └── requirements.txt
├── shared/
│   └── python/
│       └── ai_lab_common/
│           └── config.py              # Centralized settings (env vars → singleton)
├── infra/
│   ├── docker/
│   │   ├── docker-compose.yml         # ai-app VM (nginx + gateway + chat UI)
│   │   ├── docker-compose.data.yml    # ai-data VM (Postgres + Qdrant)
│   │   └── nginx/
│   │       └── default.conf           # Reverse proxy config
│   └── migrations/
│       ├── 001_conversations.sql      # conversations + messages tables
│       ├── 002_documents.sql          # documents table (RAG metadata)
│       ├── 003_users.sql              # users table + conversations.user_id FK
│       ├── 004_user_admin.sql         # is_admin column
│       ├── 005_user_delete_cascade.sql
│       └── 006_user_child_flag.sql    # is_child column (for future guardrails)
└── scripts/
    ├── run_local.sh                   # Local dev (interactive)
    ├── deploy-app.sh                  # Deploy gateway + chat UI
    ├── deploy-data.sh                 # Deploy Postgres + Qdrant
    ├── aictl.sh                       # Unified service control
    ├── ingest.py                      # CLI tool for document ingestion
    ├── eval.py                        # Eval runner (terminal output + optional JSON)
    └── eval_weave.py                  # Eval runner (tracked in W&B Weave dashboard)
```

## Tech Stack

Python 3.12, FastAPI, Streamlit, httpx, Ollama, Postgres 16 (asyncpg), Qdrant, bcrypt, W&B Weave, pypdf, MCP (Model Context Protocol), Docker Compose

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full learning path and phase details.

**Completed:** Phase 1 (Chat Platform) → Phase 2 (Homelab Deploy) → Phase 3 (Data Layer) → Phase 3.5 (Consolidation) → Phase 4 (RAG) → Phase 4.5 (Auth & UX) → Phase 5 (Evaluation) → Phase 6 (Tool Use) → Phase 6.5 (MCP)

**Next:** Phase 7 (Agents) or child guardrails

**Future:** Multi-agent systems
