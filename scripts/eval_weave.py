#!/usr/bin/env python3
"""
AI Lab — Weave Evaluation Runner (Phase 5)

Like eval.py, but results are tracked in W&B Weave — versioned datasets,
model configs, scorer results, and per-prediction logs. Use this when you
want to compare runs over time in the Weave dashboard.

Usage:
    # Evaluate all models on general + code datasets
    python scripts/eval_weave.py

    # Evaluate a specific model
    python scripts/eval_weave.py --models mistral:7b

    # Include RAG tests
    python scripts/eval_weave.py --categories general,code,rag

    # Use a specific judge model for consistent scoring
    python scripts/eval_weave.py --judge-model mistral:7b

    # Custom gateway URL
    python scripts/eval_weave.py --gateway http://192.168.1.100/api

Prerequisites:
    pip install weave wandb httpx

How it works:
    Weave Evaluation ties three things together:
    1. A Model — wraps your gateway, tracks config (model name, temperature)
    2. A Dataset — your test cases, versioned in Weave
    3. Scorers — grading functions tracked as Weave ops

    Every eval run is logged to the Weave dashboard. You can compare runs,
    see per-prediction results, and track quality over time — no manual
    JSON file management needed.

    The Weave dashboard is at: https://wandb.ai/<your-entity>/ai-lab/weave
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import weave

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_GATEWAY = os.getenv("GATEWAY_URL", "http://localhost/api")
DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "eval"
EVAL_TEMPERATURE = 0.3
REQUEST_TIMEOUT = 120.0

JUDGE_PROMPT = """You are an AI response evaluator. Rate how well an AI assistant answered a question.

## Question:
{question}

## Criteria for a good answer:
{criteria}

## The AI's response:
{response}

## Instructions:
Rate 1-5:
- 1: Completely wrong or irrelevant
- 2: Partially relevant but major errors
- 3: Acceptable but misses important points
- 4: Good — accurate and covers criteria well
- 5: Excellent — thorough, accurate, matches all criteria

Respond with ONLY a JSON object: {{"score": <1-5>, "reason": "<one sentence>"}}"""


# ---------------------------------------------------------------------------
# Weave Model — wraps the gateway
# ---------------------------------------------------------------------------


class GatewayModel(weave.Model):
    """Wraps the LLM Gateway as a Weave Model.

    Weave tracks the model config (name, temperature, gateway URL) alongside
    eval results. If you change any of these and re-run, Weave shows the diff.
    """

    model_name: str
    temperature: float = EVAL_TEMPERATURE
    gateway_url: str = DEFAULT_GATEWAY

    @weave.op
    def predict(self, question: str, category: str = "general") -> dict:
        """Send a question to the gateway and return the response + latency."""
        use_rag = category == "rag"
        payload = {
            "message": question,
            "model": self.model_name,
            "temperature": self.temperature,
            "use_rag": use_rag,
        }
        start = time.time()
        resp = httpx.post(
            f"{self.gateway_url}/chat",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        latency = round(time.time() - start, 2)
        data = resp.json()
        return {
            "response": data["response"],
            "model": data["model"],
            "latency_s": latency,
        }


# ---------------------------------------------------------------------------
# Weave Scorers — tracked grading functions
# ---------------------------------------------------------------------------


@weave.op
def keyword_score(expected_keywords: list, output: dict) -> dict:
    """Check what fraction of expected keywords appear (word-boundary match).

    This is a sanity baseline — if the response doesn't mention key terms,
    something is probably wrong. But it doesn't replace the judge scorer
    (a response can use synonyms and still be correct).
    """
    if not expected_keywords:
        return {"keyword_score": 1.0, "keyword_matches": []}

    response_lower = output["response"].lower()
    matches = []
    for kw in expected_keywords:
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", response_lower):
            matches.append(kw)

    return {
        "keyword_score": len(matches) / len(expected_keywords),
        "keyword_matches": matches,
    }


def make_judge_scorer(gateway_url: str, judge_model: str):
    """Create an LLM-as-judge scorer bound to a specific gateway and model.

    We use a factory because the judge needs gateway_url and judge_model,
    but Weave scorers receive only the dataset row + model output.
    """

    @weave.op
    def judge_score(question: str, criteria: str, output: dict) -> dict:
        """Ask an LLM to rate the response 1-5 against the grading criteria."""
        prompt = JUDGE_PROMPT.format(
            question=question,
            criteria=criteria,
            response=output["response"],
        )
        try:
            resp = httpx.post(
                f"{gateway_url}/chat",
                json={
                    "message": prompt,
                    "model": judge_model,
                    "temperature": 0.1,
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            judge_text = resp.json()["response"].strip()

            start = judge_text.find("{")
            end = judge_text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(judge_text[start:end])
                score = int(parsed.get("score", 0))
                reason = parsed.get("reason", "no reason given")
                if 1 <= score <= 5:
                    return {"judge_score": score, "judge_reason": reason}
            return {"judge_score": 0, "judge_reason": f"Could not parse: {judge_text[:100]}"}
        except Exception as e:
            return {"judge_score": 0, "judge_reason": f"Judge failed: {e}"}

    return judge_score


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_weave_dataset(categories: list[str], name: str = "ai-lab-eval") -> weave.Dataset:
    """Load test cases from JSON files and wrap them as a Weave Dataset.

    Weave versions the dataset — if you add/change test cases and re-run,
    Weave tracks the new version and lets you compare results across versions.
    """
    rows = []
    for cat in categories:
        path = DATASETS_DIR / f"{cat}.json"
        if not path.exists():
            print(f"  Warning: {path} not found, skipping")
            continue
        with open(path) as f:
            data = json.load(f)
        print(f"  Loaded {len(data['cases'])} cases from {cat}.json")
        for case in data["cases"]:
            rows.append({
                "id": case["id"],
                "category": data["category"],
                "question": case["question"],
                "criteria": case["criteria"],
                "expected_keywords": case.get("expected_keywords", []),
            })
    return weave.Dataset(name=name, rows=rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_models(gateway_url: str) -> list[str]:
    resp = httpx.get(f"{gateway_url}/models", timeout=10.0)
    resp.raise_for_status()
    return resp.json()["models"]


def check_documents(gateway_url: str) -> int | None:
    try:
        resp = httpx.get(f"{gateway_url}/documents", timeout=10.0)
        resp.raise_for_status()
        return len(resp.json().get("documents", []))
    except Exception as exc:
        print(f"  Warning: could not query documents: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="AI Lab Weave Eval — tracked evaluation with W&B Weave dashboard",
    )
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY, help="Gateway URL")
    parser.add_argument("--models", help="Comma-separated models (default: all available)")
    parser.add_argument("--categories", default="general,code", help="Dataset categories")
    parser.add_argument("--judge-model", help="Model for LLM-as-judge (default: model being tested)")
    parser.add_argument("--project", default="ai-lab", help="Weave project name")
    args = parser.parse_args()

    gateway_url = args.gateway.rstrip("/")
    categories = [c.strip() for c in args.categories.split(",")]

    # Check WANDB_API_KEY
    if not os.environ.get("WANDB_API_KEY"):
        print("ERROR: WANDB_API_KEY not set. Get yours at https://wandb.ai/authorize")
        sys.exit(1)

    # Verify gateway
    print("Connecting to gateway...")
    try:
        health = httpx.get(f"{gateway_url}/health", timeout=5.0).json()
        print(f"  Gateway: OK (db={health.get('database')}, vectors={health.get('vector_store')})")
    except Exception as e:
        print(f"  ERROR: Cannot reach gateway at {gateway_url}: {e}")
        sys.exit(1)

    # Resolve models
    if args.models:
        models = [m.strip() for m in args.models.split(",")]
    else:
        models = get_models(gateway_url)
        print(f"  Models: {', '.join(models)}")

    if not models:
        print("No models available.")
        sys.exit(1)

    # RAG check
    if "rag" in categories:
        doc_count = check_documents(gateway_url)
        if doc_count is None:
            vs_ok = health.get("vector_store", False)
            if vs_ok:
                print("  Could not query document count, but vector store is healthy — running RAG tests")
            else:
                print("  Vector store unavailable — skipping RAG tests")
                categories = [c for c in categories if c != "rag"]
        elif doc_count == 0:
            print("  No documents ingested — skipping RAG tests")
            categories = [c for c in categories if c != "rag"]
        else:
            print(f"  Documents: {doc_count} — RAG tests enabled")

    # Initialize Weave
    print(f"\nInitializing Weave (project: {args.project})...")
    weave.init(args.project)

    # Load dataset (Weave versions it automatically)
    print("\nLoading test cases...")
    dataset = load_weave_dataset(categories)
    print(f"  Total: {len(dataset.rows)} test cases")

    # Build scorers
    # The keyword scorer works for all models. The judge scorer needs
    # a specific model — if none specified, we create per-model judges.
    scorers = [keyword_score]

    # Run evaluation for each model
    for model_name in models:
        judge_model = args.judge_model or model_name
        judge_scorer = make_judge_scorer(gateway_url, judge_model)
        model_scorers = scorers + [judge_scorer]

        print(f"\n{'='*60}")
        print(f"  Evaluating: {model_name} (judge: {judge_model})")
        print(f"{'='*60}")

        model = GatewayModel(
            model_name=model_name,
            temperature=EVAL_TEMPERATURE,
            gateway_url=gateway_url,
        )

        evaluation = weave.Evaluation(
            name=f"eval-{model_name.replace(':', '-')}",
            dataset=dataset,
            scorers=model_scorers,
        )

        import asyncio
        asyncio.run(evaluation.evaluate(model))

    print(f"\nDone. View results at: https://wandb.ai/weave → project '{args.project}'")


if __name__ == "__main__":
    main()
