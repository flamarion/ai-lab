# AI Lab — Learning Roadmap

Goal: Build a mini AI platform from scratch, learning end-to-end AI system design.
End goal: An agentic system running on homelab infrastructure.

## Architecture Target

```
You → Chat UI → LLM Gateway → Ollama (GPU PC)
                    ↓    ↑
               Tool Layer (APIs, DB, search)
                    ↓
              Agent Orchestrator
               ↓         ↓
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

### Phase 3 — Data Layer
**What you'll build:** Qdrant (vector DB) + Postgres on ai-data VM
**What you'll learn:**
- What embeddings are and why they matter
- Vector databases vs relational databases — when to use each
- How to persist AI application state (conversations, user data)
- Cross-VM service communication

**Infrastructure:**
- ai-data VM: Qdrant + Postgres

---

### Phase 4 — RAG Pipeline
**What you'll build:** Document ingestion → chunking → embedding → retrieval → augmented generation
**What you'll learn:**
- How LLMs get grounded in real data (not just training knowledge)
- Chunking strategies and why they matter
- Embedding models and similarity search
- Prompt engineering with retrieved context
- The difference between "knows everything" and "can look things up"

---

### Phase 5 — Evaluation
**What you'll build:** Test cases, scoring, model comparison (mistral vs llama3)
**What you'll learn:**
- How to measure if your AI system is actually good
- Automated evaluation vs human evaluation
- Building test datasets
- Regression testing for AI (did your change make things worse?)

---

### Phase 6 — Tool Use & Function Calling
**What you'll build:** Gateway supports tools (web search, DB queries, calculations)
**What you'll learn:**
- How models take actions, not just generate text
- Function calling / tool use protocols
- Safety: what happens when a model calls a dangerous tool?
- The bridge from "chatbot" to "assistant"

---

### Phase 7 — Agents
**What you'll build:** Orchestration loop — plan → act → observe → repeat
**What you'll learn:**
- Autonomous AI systems and the agent loop
- Memory: short-term (conversation) vs long-term (persisted)
- Planning and reasoning strategies
- When to stop: exit conditions and guardrails

---

### Phase 8 — Multi-Agent Systems
**What you'll build:** Specialized agents that collaborate on complex tasks
**What you'll learn:**
- Task decomposition and delegation
- Agent-to-agent communication
- Coordination patterns (hierarchical, peer-to-peer)
- Building reliable systems from unreliable components
