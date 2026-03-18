# Practical AI Lab — Overview

## 🎯 Goal

Build your own **mini AI platform from scratch**, similar to how a company would — but running entirely in your home lab.

---

## 🧠 Core Idea

This is not about “playing with models”.

It's about learning how to build a **real AI system end-to-end**: User → App → Model → Data → Evaluation → Improvement

---

## 🧠 What You’re Actually Learning

You’re developing **systems thinking for AI**, not just coding skills.

You will learn how to:

- Run models locally (inference)
- Build applications on top of them
- Add knowledge (RAG)
- Orchestrate behavior (agents)
- Improve models (fine-tuning)
- Measure everything (observability with W&B)

---

## 🧱 The 5-Layer Mental Model

### 1. Inference
> How do I run models?

- Ollama, vLLM
- GPU usage
- Latency vs quality tradeoffs

---

### 2. Application
> How do users interact with it?

- Streamlit / APIs
- Prompt structure
- UX for AI systems

---

### 3. Knowledge (RAG)
> How does it know things?

- Documents
- Embeddings
- Vector DB (Qdrant)
- Retrieval + reranking

---

### 4. Reasoning (Agents)
> How does it *do things*?

- Tools
- Workflows
- Decision-making

---

### 5. Evaluation & Observability
> How do I know if it’s good?

- W&B Weave traces
- Datasets
- Scoring
- Regression testing

---

## 🔁 The Core Loop

Instead of guessing, you build a **feedback loop**: Build → Measure → Improve → Repeat

NOT: Build → vibe-check → change random things → repeat 😅

---

## 🏗️ Your Advantage (Homelab Setup)

You already have:

- GPUs → local inference + training
- Proxmox → isolation and structure
- Ceph → real data layer (huge advantage)
- W&B → professional-grade observability

👉 This is essentially a **mini AI company infrastructure**

---

## 🚫 What This Is NOT

- Not just building a chatbot
- Not trying random frameworks
- Not copying tutorials blindly

---

## ✅ What This IS

👉 Learning how **real AI systems work in production**

---

## 🧭 Learning Stages

### Stage 1 (Now)
- Basic app + model + tracing
- Understand the full request flow

---

### Stage 2
- RAG (real knowledge system)

---

### Stage 3
- Agents (structured behavior)

---

### Stage 4
- Fine-tuning (custom intelligence)

---

### Stage 5
- Optimization + scaling

---

## 🧠 Mindset Shift

### From:
> “Which model is best?”

### To:
> “Which system design produces the best results?”

---

## 🧩 One-Line Summary

👉 You are building a **personal AI engineering lab** to understand how to design, evaluate, and improve intelligent systems end-to-end.


## Repository layout

```
ai-lab/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── architecture.md
│   └── roadmap.md
├── infra/
│   └── docker/
│       ├── app/docker-compose.yml
│       └── data/docker-compose.yml
├── apps/
│   └── chat-ui/
│       ├── app.py
│       ├── requirements.txt
│       └── Dockerfile
├── services/
│   └── llm-gateway/
│       ├── src/
│       │   ├── main.py
│       │   ├── ollama_client.py
│       │   └── tracing.py
│       ├── requirements.txt
│       └── Dockerfile
├── shared/
│   └── python/
│       └── ai_lab_common/
│           ├── config.py
│           └── tracing.py
├── datasets/
│   └── eval/
└── scripts/
    ├── bootstrap.sh
    └── run_local.sh
```