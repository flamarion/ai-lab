# AI Lab — Learning Roadmap

Goal: Build a mini AI platform from scratch, learning end-to-end AI system design.
End goal: An agentic system running on homelab infrastructure.

## Current Architecture

```
┌─── ai-app VM (Proxmox) ──────────────────────────────────┐
│                                                           │
│  ┌──────────┐    HTTP     ┌──────────────────────────┐   │
│  │ Chat UI  │────────────▶│      LLM Gateway         │   │
│  │ :8501    │◀────────────│      :8000               │   │
│  └──────────┘             │                          │   │
│                           │  • /chat (+ system prompt,│   │
│                           │    top_p, num_predict)    │   │
│                           │  • /models               │   │
│                           │  • /conversations        │   │
│                           └──────┬───────────┬───────┘   │
│                                  │           │           │
└──────────────────────────────────┼───────────┼───────────┘
                                   │           │
                            LAN    │           │  LAN
                                   ▼           ▼
┌─── mato (GPU PC) ────────────┐  ┌─── ai-data VM ────────┐
│                               │  │                        │
│  Ollama :11434                │  │  Postgres :5432        │
│  ├── mistral:7b               │  │  ├── conversations     │
│  ├── qwen3.5:latest           │  │  └── messages          │
│  ├── llama3.1:8b              │  │                        │
│  └── gemma3:12b               │  │                        │
│                               │  │  Qdrant :6333  (P4)    │
│  2x RTX 3060 12GB (24GB)     │  │                        │
│  Flash attn, q8 KV, 16k ctx  │  │                        │
└───────────────────────────────┘  └────────────────────────┘
```

## Architecture Target

```
Chat UI ──▶ LLM Gateway ──▶ Ollama (GPU PC)
                │    ▲
                │    │ context
                ▼    │
            Tool Layer (APIs, DB, vector search)
                │
                ▼
          Agent Orchestrator
           ▼         ▼
     Qdrant        Postgres
   (vectors)       (state)
```

## Phases

### Phase 1 — Chat Platform ✅
**What you built:** Gateway + Chat UI + Ollama + W&B Weave tracing
**What you learned:**
- How AI apps are structured (UI → API → model)
- The gateway pattern: apps never talk to models directly
- Tracing/observability with Weave — seeing what your system actually does
- Docker Compose for multi-service apps
- Shared config management across services

**Key files:**
- `services/llm-gateway/` — FastAPI gateway that abstracts Ollama
- `apps/chat-ui/` — Streamlit frontend
- `shared/python/ai_lab_common/` — shared config module
- `infra/docker/docker-compose.yml` — service orchestration

---

### Phase 2 — Deploy to Homelab ✅
**What you built:** Deployment script for ai-app VM, LAN-accessible services
**What you learned:**
- Services talk across machines via LAN IP:port — no service mesh or magic needed
- Docker internal DNS (container names as hostnames) only works within the same compose stack
- `0.0.0.0` binding = reachable from the network, not just localhost
- `git pull --ff-only` prevents accidental merges on a deploy target
- `docker compose up -d` = containers survive your SSH session ending
- `restart: unless-stopped` handles reboots without systemd

**Key files:**
- `scripts/deploy-app.sh` — pull, build, and deploy on the ai-app VM
- `scripts/run_local.sh` — local dev (interactive, not detached)

---

### Phase 3 — Data Layer (Postgres Conversation Persistence) ✅
**What you built:** Postgres on ai-data VM, conversation persistence in the gateway, sidebar history in Chat UI
**What you learned:**
- Cross-VM service communication over LAN — same pattern as Ollama (LAN IP:port in env vars)
- Postgres Docker initialization pattern (`/docker-entrypoint-initdb.d/` runs SQL files on first start)
- Connection pooling with asyncpg — `min_size`/`max_size` control how many connections stay open for async reuse
- Upsert pattern (`INSERT ... ON CONFLICT`) for idempotent operations — safe to retry without duplicates
- Graceful degradation — gateway starts and serves requests even if Postgres is unreachable
- Compose file split — separate compose per VM (`docker-compose.yml` for ai-app, `docker-compose.data.yml` for ai-data)
- `ON DELETE CASCADE` — deleting a conversation automatically removes its messages, DB enforces referential integrity

**Key files:**
- `infra/docker/docker-compose.data.yml` — Postgres compose for ai-data VM
- `infra/migrations/001_conversations.sql` — conversations + messages schema
- `scripts/deploy-data.sh` — deploy script for data services
- `services/llm-gateway/src/db.py` — asyncpg connection pool and query functions
- `services/llm-gateway/src/main.py` — /chat persistence + /conversations endpoints
- `apps/chat-ui/app.py` — sidebar with conversation history

---

### Phase 3.5 — Consolidation & User Controls ✅
**What you built:** System prompt, top_p, max tokens controls; auto model selection; Ollama tuning docs; config cleanup; unified `aictl.sh` control script
**What you learned:**
- Pass-through options pattern: gateway validates and builds an options dict, client transports it as-is, Ollama handles arbitrary keys. Adding a new parameter only requires a change in one place (the gateway's request model).
- UI progressive disclosure: `st.expander("Advanced")` hides power-user controls from casual users — family members see only Model and Temperature.
- System prompts are the simplest way to customize LLM behavior without code changes — "reply in Portuguese" or "explain like I'm 10."
- Auto model selection: fallback chain (request → env var → first available) makes the system work without any model configuration.
- Ollama performance tuning: flash attention + q8 KV cache quantization makes 16k context viable on 12GB VRAM.

**Key files:**
- `services/llm-gateway/src/main.py` — expanded ChatRequest, options dict builder, system prompt injection
- `services/llm-gateway/src/ollama_client.py` — refactored to accept options dict
- `apps/chat-ui/app.py` — Advanced expander with top_p, num_predict, system_prompt
- `scripts/aictl.sh` — unified service control
- `CLAUDE.md` — Ollama tuning docs

---

### Phase 4 — RAG Pipeline ✅
**What you built:** Document ingestion (PDF, text, markdown, code), chunking, embedding, vector search, RAG-augmented chat

```
Phase 4 data flow:

  your docs                    user question
  (PDF, md, txt, code)         "what does X say about Y?"
       │                              │
       ▼                              ▼
┌─────────────┐              ┌──────────────┐
│  Ingestion  │              │  LLM Gateway │
│  Pipeline   │              │              │
│ load → chunk│              │  1. embed    │
│ → embed     │              │     question │
│ → store     │              │  2. search   │──▶ Qdrant
└──────┬──────┘              │     Qdrant   │◀── top-k chunks
       │                     │  3. build    │
       ▼                     │     prompt   │
    Qdrant                   │  4. call     │──▶ Ollama
    (vectors)                │     Ollama   │◀── answer
                             └──────────────┘

Embedding model: nomic-embed-text-v2-moe (958MB, MoE, 768 dims)
Vector store:    Qdrant (Docker on ai-data VM)
```

**What you learned:**
- RAG grounds LLMs in real data — the model looks things up instead of guessing
- Chunking strategies: split on paragraphs first, then sentences, with overlap for context continuity
- Embedding models turn text into vectors — "meaning" becomes a number you can search
- Cosine similarity finds semantically related content, not just keyword matches
- The RAG prompt template is critical — it instructs the model to use context and admit when it doesn't know
- Embedding prefixes matter: `search_document:` for chunks, `search_query:` for questions (model-specific optimization)
- Qdrant payloads store the original text alongside vectors — you need both for retrieval
- Graceful degradation extends to vector stores — chat works without Qdrant, RAG just becomes unavailable

**Key files:**
- `services/llm-gateway/src/vector_store.py` — Qdrant wrapper (init, upsert, search, delete)
- `services/llm-gateway/src/chunker.py` — document loading (text, PDF, code) and chunking
- `services/llm-gateway/src/ollama_client.py` — `embed()` method for Ollama /api/embed
- `services/llm-gateway/src/main.py` — /ingest, /documents endpoints, RAG in /chat
- `infra/docker/docker-compose.data.yml` — Qdrant service on ai-data VM
- `infra/migrations/002_documents.sql` — documents table
- `scripts/ingest.py` — CLI tool for bulk document ingestion
- `apps/chat-ui/app.py` — RAG toggle in Advanced settings

---

### Phase 4.5 — UX Polish: Auth, Admin, File Upload ✅
**What you built:** PIN-based user authentication, per-user conversations, admin panel, file upload in chat, settings persistence, simplified UI for family use
**What you learned:**
- Multi-user architecture: adding a `user_id` FK to conversations, filtering queries, nullable for backward compatibility
- PIN auth with bcrypt: hash on register, verify on login, run in threadpool to avoid blocking async event loop
- Admin role pattern: first registered user is auto-admin, admin endpoints validate caller before acting
- Database migrations handle schema evolution — adding columns, changing FK constraints across deploys
- UI progressive disclosure: family members see Model + Temperature, power users open Advanced for RAG, system prompt, file upload
- Settings persistence via JSONB column — preferences follow the user across devices
- Copilot review triage: fix real bugs (FK violations, XSS, event loop blocking), deprioritize auth hardening for LAN apps

**Key files:**
- `infra/migrations/003_users.sql` — users table + conversations.user_id
- `infra/migrations/004_user_admin.sql` — is_admin column
- `infra/migrations/005_user_delete_cascade.sql` — ON DELETE SET NULL fix
- `services/llm-gateway/src/main.py` — auth, admin, change-pin endpoints
- `apps/chat-ui/app.py` — login screen, admin panel, PIN change, file upload

---

### Phase 5 — Evaluation ✅
**What you built:** Eval datasets, LLM-as-judge scoring, keyword checks, model comparison runner

```
Phase 5 eval flow:

  datasets/eval/*.json          scripts/eval.py
  (test cases with criteria)    (eval runner)
       │                              │
       ▼                              ▼
  ┌──────────────────────────────────────────┐
  │  For each model × each test case:        │
  │  1. POST /chat → get response            │
  │  2. Keyword score (expected terms found?) │
  │  3. LLM-as-judge (model rates 1-5)       │
  │  4. Record latency                        │
  └──────────────────────────────────────────┘
       │
       ▼
  Comparison table (avg scores by model, by category, notable differences)
```

**What you learned:**
- LLM-as-judge: using one model to grade another's output — the standard production eval approach. Scales better than human review and catches nuance that keyword matching misses
- Test dataset design: each case has a question, criteria for grading, and optional expected keywords. Criteria describe *what good looks like*, not just right/wrong
- Keyword scoring is a sanity check, not a replacement for judge scoring — a response can use synonyms and still be correct
- Eval should test the whole system (gateway → routing → model), not just raw model output — that's why the runner hits `/chat`
- Self-judging (each model judges itself) is fair for comparison; cross-model judging (one model judges all) is better for consistency
- Low temperature during eval (0.3) and judging (0.1) reduces randomness so results are more reproducible
- Weave Evaluation framework: `weave.Model` tracks config, `weave.Dataset` versions test cases, `@weave.op` scorers are logged — every run becomes a tracked experiment you can compare in the dashboard

**Key files:**
- `datasets/eval/general.json` — general knowledge and reasoning (8 cases)
- `datasets/eval/code.json` — code generation and technical reasoning (8 cases)
- `datasets/eval/rag.json` — RAG-dependent questions (3 cases, skipped if no docs)
- `scripts/eval.py` — standalone eval runner (terminal output + optional JSON)
- `scripts/eval_weave.py` — Weave-tracked eval runner (dashboard with versioned results)

---

### Phase 6 — Tool Use & Function Calling ✅
**What you built:** Tool registry, tool execution loop in gateway, calculator + current_time tools, Chat UI tools toggle

```
Phase 6 tool-use flow:

  User: "What's 2847 * 391?"
       │
       ▼
  ┌──────────────────────────────────────────────────┐
  │  Gateway sends message + tool schemas to Ollama  │
  │                                                  │
  │  Ollama returns: tool_calls: [                   │
  │    {calculator, {expression: "2847 * 391"}}      │
  │  ]                                               │
  │                                                  │
  │  Gateway executes: calculator("2847 * 391")      │
  │  → "1113177"                                     │
  │                                                  │
  │  Gateway feeds result back to Ollama             │
  │  Ollama returns: "2847 × 391 = 1,113,177"       │
  └──────────────────────────────────────────────────┘
```

**What you learned:**
- Tool use protocol: model doesn't run tools — it *requests* them. The gateway orchestrates: send tools → get tool_calls → execute → feed result back → get final answer
- Not all models support tool use: llama3.1+, qwen3.5, gemma3 do; mistral:7b (raw mode only), llama3 (none). The model itself must support the tool_calls response format
- Tool schemas use JSON Schema (same as OpenAI function calling) — the model reads the description to decide when to call each tool
- Multi-round tool use: the model can call tools multiple times in sequence (up to max_tool_rounds)
- Safe eval for calculator: compile to AST, whitelist allowed names, no arbitrary code execution


**Key files:**
- `services/llm-gateway/src/tools.py` — tool registry (calculator, current_time) + execution
- `services/llm-gateway/src/ollama_client.py` — `chat_with_tools()` method (tool call loop)
- `services/llm-gateway/src/main.py` — `use_tools` flag in ChatRequest, `/tools` endpoint
- `apps/chat-ui/app.py` — tools toggle in Settings, tool usage display in chat

---

### Phase 6.5 — MCP (Model Context Protocol) ✅
**What you built:** MCP client in the gateway, hybrid tool architecture (local + MCP), configurable server connections, admin UI, secrets store, Cursor-style config import

```
Phase 6.5 hybrid tool architecture:

  Model → Gateway → MCP Client Manager → mcp-server-fetch (URL reader)
                                        → wandb, kubernetes, etc. via config
                  → tools.py (calculator, current_time, unit_convert)

  Config persisted in Postgres (survives container restarts)
  Admin UI: add/edit/remove servers, Cursor-style JSON import
  Secrets: ${SECRET_NAME} inline, ${file:SECRET_NAME} for kubeconfig/certs
```

**What you learned:**
- MCP is "USB for AI tools" — a standard protocol for tool discovery and execution. Any MCP server works with any MCP client (Claude Code, Cursor, etc.)
- Hybrid architecture: MCP for general-purpose tools (web, GitHub, databases), local tools.py for custom/homelab-specific functions
- Cursor-style config format: same JSON used in Cursor, Claude Desktop, VS Code — paste and import
- Three transports: stdio (subprocess), HTTP (streamable), SSE (legacy). Gateway tries all automatically
- Secrets store: API keys in Postgres, ${SECRET_NAME} for inline substitution, ${file:SECRET_NAME} for file-based secrets (kubeconfig, certificates)
- MCP config persistence: stored in Postgres, survives container restarts. JSON file is fallback only
- Why standards exist: building custom tools first (Phase 6) made the value of MCP obvious

**Key files:**
- `services/llm-gateway/src/mcp_client.py` — MCP client manager (connect, discover, route, secret substitution)
- `services/llm-gateway/src/tools.py` — local tools (calculator, current_time, unit_convert)
- `services/llm-gateway/src/main.py` — MCP + secrets CRUD endpoints
- `apps/web-ui/src/app/admin/page.tsx` — admin UI for servers, secrets, users

---

### Phase 7 — Agents
**What you'll build:** Orchestration loop — plan → act → observe → repeat
**What you'll learn:**
- Autonomous AI systems and the agent loop
- Memory: short-term (conversation) vs long-term (persisted)
- Planning and reasoning strategies
- When to stop: exit conditions and guardrails

---

### Phase 7.5 — Web Search (SearXNG or Ollama)
**What you'll build:** Proper web search capability — either self-hosted SearXNG or Ollama's cloud search API
**What you'll learn:**
- SearXNG: self-hosted meta search engine (aggregates Google, Bing, DuckDuckGo). Docker container on ai-app VM, JSON API, no API keys needed. Fully local.
- Ollama web search: cloud API with search + fetch. Simpler setup but requires Ollama API key and internet access to their proxy.
- The current MCP `fetch` tool reads URLs but can't search — different problem. Search finds relevant URLs, fetch reads them.
- Decision: SearXNG fits the local-first homelab philosophy. Ollama search is the easy path if external dependency is acceptable.

---

### Phase 8 — Multi-Agent Systems
**What you'll build:** Specialized agents that collaborate on complex tasks
**What you'll learn:**
- Task decomposition and delegation
- Agent-to-agent communication
- Coordination patterns (hierarchical, peer-to-peer)
- Building reliable systems from unreliable components
