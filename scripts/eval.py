#!/usr/bin/env python3
"""
AI Lab — Evaluation Runner (Phase 5)

Runs test cases against the LLM Gateway, scores responses using LLM-as-judge,
and produces a model comparison report.

Usage:
    # Compare all available models on general + code datasets
    python scripts/eval.py

    # Test a specific model
    python scripts/eval.py --models mistral:7b

    # Test multiple models
    python scripts/eval.py --models mistral:7b,qwen3.5:latest

    # Run only code tests
    python scripts/eval.py --categories code

    # Include RAG tests (requires ingested documents)
    python scripts/eval.py --categories general,code,rag

    # Use a different gateway URL (e.g. from another machine on the LAN)
    python scripts/eval.py --gateway http://192.168.1.100/api

    # Save results to a JSON file
    python scripts/eval.py --output results.json

Prerequisites:
    pip install -r scripts/requirements.txt

How it works:
    1. Loads test cases from datasets/eval/*.json
    2. For each model, sends each test case to POST /chat
    3. Scores each response two ways:
       - Keyword check: do expected keywords appear in the response?
       - LLM-as-judge: asks a model to rate the response 1-5 on the criteria
    4. Prints a summary table comparing models

LLM-as-judge explained:
    Instead of manually reading every answer, we use a model to grade responses.
    The judge sees the question, the criteria for a good answer, and the actual
    response — then rates it 1-5. This is the standard approach in production
    eval pipelines because:
    - It scales (you can evaluate thousands of responses)
    - It's more consistent than human grading
    - It catches nuance that keyword matching misses
    The judge model is configurable (defaults to the same model being tested,
    but you can set --judge-model for consistency).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from repo root so scripts pick up GATEWAY_URL, etc.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost/api")
DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets" / "eval"
EVAL_TEMPERATURE = 0.3  # low temperature for more deterministic responses
JUDGE_TEMPERATURE = 0.1  # very low for consistent scoring
REQUEST_TIMEOUT = 300.0  # seconds — must be >= nginx proxy_read_timeout (300s)
RETRY_ATTEMPTS = 3
RETRY_DELAY = 10  # seconds — gives Ollama time to load a new model

# The judge prompt — this is the core of LLM-as-judge evaluation.
# It instructs the model to act as a grader and return a structured score.
JUDGE_PROMPT = """You are an AI response evaluator. Your job is to rate how well an AI assistant answered a question.

## Question that was asked:
{question}

## Criteria for a good answer:
{criteria}

## The AI's actual response:
{response}

## Instructions:
Rate the response from 1 to 5:
- 1: Completely wrong, irrelevant, or harmful
- 2: Partially relevant but has major errors or missing key information
- 3: Acceptable — covers the basics but misses important points
- 4: Good — accurate and covers the criteria well
- 5: Excellent — thorough, accurate, well-explained, and matches all criteria

Respond with ONLY a JSON object in this exact format:
{{"score": <1-5>, "reason": "<one sentence explaining your score>"}}"""


# ---------------------------------------------------------------------------
# Gateway client
# ---------------------------------------------------------------------------


def _post_with_retry(url: str, **kwargs) -> httpx.Response:
    """POST with retry for transient errors (502/504).

    When Ollama switches models, the first request often fails because it
    needs to unload one model and load another into VRAM. Retrying after
    a short delay handles this gracefully.
    """
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        resp = httpx.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
        if resp.status_code in (502, 504) and attempt < RETRY_ATTEMPTS:
            print(f"\n    Retry {attempt}/{RETRY_ATTEMPTS} (got {resp.status_code}, "
                  f"waiting {RETRY_DELAY}s for model load)...", end=" ", flush=True)
            time.sleep(RETRY_DELAY)
            continue
        resp.raise_for_status()
        return resp
    return resp  # unreachable, but keeps type checkers happy


def chat(
    gateway_url: str,
    message: str,
    model: str,
    temperature: float = EVAL_TEMPERATURE,
    use_rag: bool = False,
) -> dict:
    """Send a chat request to the gateway and return the response."""
    payload = {
        "message": message,
        "model": model,
        "temperature": temperature,
        "use_rag": use_rag,
    }
    resp = _post_with_retry(
        f"{gateway_url}/chat",
        json=payload,
    )
    return resp.json()


def get_models(gateway_url: str) -> list[str]:
    """Fetch available models from the gateway."""
    resp = httpx.get(f"{gateway_url}/models", timeout=10.0)
    resp.raise_for_status()
    return resp.json()["models"]


def check_documents(gateway_url: str) -> int | None:
    """Check how many documents are ingested (for RAG eval).

    Returns the document count, or None if the endpoint is unreachable
    (so callers can distinguish 'no docs' from 'can't tell').
    """
    try:
        resp = httpx.get(f"{gateway_url}/documents", timeout=10.0)
        resp.raise_for_status()
        return len(resp.json().get("documents", []))
    except Exception as exc:
        print(f"  Warning: could not query {gateway_url}/documents: {exc}")
        return None


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_datasets(categories: list[str]) -> list[dict]:
    """Load test cases from JSON files in datasets/eval/."""
    all_cases = []
    for cat in categories:
        path = DATASETS_DIR / f"{cat}.json"
        if not path.exists():
            print(f"  Warning: dataset {path} not found, skipping")
            continue
        with open(path) as f:
            data = json.load(f)
        print(f"  Loaded {len(data['cases'])} cases from {cat}.json")
        for case in data["cases"]:
            case["category"] = data["category"]
        all_cases.extend(data["cases"])
    return all_cases


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_keywords(response_text: str, expected_keywords: list[str]) -> float:
    """
    Simple keyword check: what fraction of expected keywords appear in the response?

    Returns a score from 0.0 to 1.0. This is a baseline sanity check —
    if the response doesn't mention key terms, something is probably wrong.
    It doesn't replace LLM-as-judge (a response can use synonyms and still be good).
    """
    if not expected_keywords:
        return 1.0  # no keywords to check = pass
    lower_response = response_text.lower()
    matches = sum(
        1 for kw in expected_keywords
        if re.search(r"\b" + re.escape(kw.lower()) + r"\b", lower_response)
    )
    return matches / len(expected_keywords)


def score_with_judge(
    gateway_url: str,
    judge_model: str,
    question: str,
    criteria: str,
    response_text: str,
) -> dict:
    """
    LLM-as-judge: ask a model to rate the response 1-5.

    Returns {"score": int, "reason": str} or {"score": 0, "reason": "..."} on failure.

    This is the most important scoring method. Keyword matching can tell you if
    an answer mentions "gravity", but the judge can tell you if the explanation
    is actually correct, well-structured, and appropriate for the audience.
    """
    prompt = JUDGE_PROMPT.format(
        question=question,
        criteria=criteria,
        response=response_text,
    )
    try:
        result = chat(gateway_url, prompt, judge_model, temperature=JUDGE_TEMPERATURE)
        judge_text = result["response"].strip()

        # Extract JSON from the response (handle models that add extra text)
        # Look for the first { ... } block
        start = judge_text.find("{")
        end = judge_text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(judge_text[start:end])
            score = int(parsed.get("score", 0))
            reason = parsed.get("reason", "no reason given")
            if 1 <= score <= 5:
                return {"score": score, "reason": reason}
        return {"score": 0, "reason": f"Could not parse judge response: {judge_text[:100]}"}
    except Exception as e:
        return {"score": 0, "reason": f"Judge call failed: {e}"}


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------


def run_eval(
    gateway_url: str,
    models: list[str],
    cases: list[dict],
    judge_model: str,
) -> dict:
    """
    Run all test cases against all models and score them.

    Returns a results dict structured as:
    {
        "model_name": {
            "results": [
                {
                    "id": "gen-001",
                    "category": "general",
                    "question": "...",
                    "response": "...",
                    "keyword_score": 0.75,
                    "judge_score": 4,
                    "judge_reason": "...",
                    "latency_s": 2.3
                },
                ...
            ],
            "summary": {"avg_judge": 3.8, "avg_keyword": 0.85, "avg_latency": 2.1}
        }
    }
    """
    all_results = {}

    for model in models:
        print(f"\n{'='*60}")
        print(f"  Evaluating: {model}")
        print(f"{'='*60}")
        model_results = []

        for i, case in enumerate(cases, 1):
            case_id = case["id"]
            question = case["question"]
            criteria = case["criteria"]
            expected_kw = case.get("expected_keywords", [])
            use_rag = case["category"] == "rag"

            print(f"  [{i}/{len(cases)}] {case_id}: {question[:60]}...", end=" ", flush=True)

            # Call the gateway
            start_time = time.time()
            try:
                result = chat(gateway_url, question, model, use_rag=use_rag)
                response_text = result["response"]
                latency = time.time() - start_time
            except httpx.HTTPStatusError as e:
                err_detail = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                print(f"ERROR: {err_detail}")
                model_results.append({
                    "id": case_id,
                    "category": case["category"],
                    "question": question,
                    "response": f"ERROR: {err_detail}",
                    "keyword_score": 0.0,
                    "judge_score": 0,
                    "judge_reason": f"Gateway error: {err_detail}",
                    "latency_s": round(time.time() - start_time, 2),
                })
                continue
            except Exception as e:
                print(f"ERROR: {e}")
                model_results.append({
                    "id": case_id,
                    "category": case["category"],
                    "question": question,
                    "response": f"ERROR: {e}",
                    "keyword_score": 0.0,
                    "judge_score": 0,
                    "judge_reason": f"Gateway error: {e}",
                    "latency_s": round(time.time() - start_time, 2),
                })
                continue

            # Score: keywords
            kw_score = score_keywords(response_text, expected_kw)

            # Score: LLM-as-judge
            judge_result = score_with_judge(
                gateway_url, judge_model, question, criteria, response_text
            )

            print(f"judge={judge_result['score']}/5  kw={kw_score:.0%}  ({latency:.1f}s)")

            model_results.append({
                "id": case_id,
                "category": case["category"],
                "question": question,
                "response": response_text,
                "keyword_score": kw_score,
                "judge_score": judge_result["score"],
                "judge_reason": judge_result["reason"],
                "latency_s": round(latency, 2),
            })

        # Compute summary
        scored = [r for r in model_results if r["judge_score"] > 0]
        avg_judge = sum(r["judge_score"] for r in scored) / len(scored) if scored else 0
        avg_kw = sum(r["keyword_score"] for r in model_results) / len(model_results) if model_results else 0
        avg_latency = sum(r["latency_s"] for r in model_results) / len(model_results) if model_results else 0

        all_results[model] = {
            "results": model_results,
            "summary": {
                "avg_judge": round(avg_judge, 2),
                "avg_keyword": round(avg_kw, 2),
                "avg_latency": round(avg_latency, 2),
                "total_cases": len(model_results),
                "judge_failures": len(model_results) - len(scored),
            },
        }

    return all_results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_comparison(results: dict) -> None:
    """Print a side-by-side model comparison table."""
    print(f"\n{'='*70}")
    print("  MODEL COMPARISON")
    print(f"{'='*70}")

    # Header
    models = list(results.keys())
    header = f"{'Metric':<22}"
    for m in models:
        header += f"  {m:>18}"
    print(header)
    print("-" * len(header))

    # Rows
    metrics = [
        ("Avg Judge Score (/5)", "avg_judge"),
        ("Avg Keyword Score", "avg_keyword"),
        ("Avg Latency (s)", "avg_latency"),
        ("Total Cases", "total_cases"),
        ("Judge Failures", "judge_failures"),
    ]
    for label, key in metrics:
        row = f"{label:<22}"
        for m in models:
            val = results[m]["summary"][key]
            if isinstance(val, float):
                row += f"  {val:>18.2f}"
            else:
                row += f"  {val:>18}"
        print(row)

    # Per-category breakdown
    categories = sorted({r["category"] for m in models for r in results[m]["results"]})
    if len(categories) > 1:
        print(f"\n{'─'*70}")
        print("  BY CATEGORY (avg judge score)")
        print(f"{'─'*70}")
        header = f"{'Category':<22}"
        for m in models:
            header += f"  {m:>18}"
        print(header)
        print("-" * len(header))

        for cat in categories:
            row = f"{cat:<22}"
            for m in models:
                cat_results = [r for r in results[m]["results"] if r["category"] == cat and r["judge_score"] > 0]
                if cat_results:
                    avg = sum(r["judge_score"] for r in cat_results) / len(cat_results)
                    row += f"  {avg:>18.2f}"
                else:
                    row += f"  {'n/a':>18}"
            print(row)

    # Highlight per-case disagreements (where models differ by 2+ points)
    if len(models) >= 2:
        print(f"\n{'─'*70}")
        print("  NOTABLE DIFFERENCES (2+ point gap between models)")
        print(f"{'─'*70}")
        case_ids = [r["id"] for r in results[models[0]]["results"]]
        found = False
        for cid in case_ids:
            scores = {}
            for m in models:
                match = next((r for r in results[m]["results"] if r["id"] == cid), None)
                if match and match["judge_score"] > 0:
                    scores[m] = match["judge_score"]
            if len(scores) >= 2:
                max_s = max(scores.values())
                min_s = min(scores.values())
                if max_s - min_s >= 2:
                    found = True
                    q = next(r["question"] for r in results[models[0]]["results"] if r["id"] == cid)
                    print(f"\n  {cid}: {q[:70]}")
                    for m, s in scores.items():
                        print(f"    {m}: {s}/5")
        if not found:
            print("  None — models performed similarly across all cases.")


def save_results(results: dict, output_path: str) -> None:
    """Save full results to a JSON file for later analysis."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models": results,
    }
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nResults saved to {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="AI Lab Eval Runner — test and compare your models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--gateway",
        default=GATEWAY_URL,
        help=f"Gateway URL (default: {GATEWAY_URL})",
    )
    parser.add_argument(
        "--models",
        help="Comma-separated list of models to test (default: all available)",
    )
    parser.add_argument(
        "--categories",
        default="general,code",
        help="Comma-separated dataset categories (default: general,code)",
    )
    parser.add_argument(
        "--judge-model",
        help="Model to use as the judge (default: same as model being tested)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Save results to a JSON file",
    )
    args = parser.parse_args()

    gateway_url = args.gateway.rstrip("/")
    categories = [c.strip() for c in args.categories.split(",")]

    # Verify gateway is reachable
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
        print(f"  Models available: {', '.join(models)}")

    if not models:
        print("No models available. Is Ollama running?")
        sys.exit(1)

    # Check for RAG documents if rag category requested
    if "rag" in categories:
        doc_count = check_documents(gateway_url)
        if doc_count is None:
            # Vector store might still have docs — check health and run with a warning
            vs_ok = health.get("vector_store", False)
            if vs_ok:
                print("  Could not query document count, but vector store is healthy — running RAG tests anyway")
            else:
                print("  Vector store unavailable — skipping RAG tests")
                categories = [c for c in categories if c != "rag"]
        elif doc_count == 0:
            print("  No documents ingested — skipping RAG tests")
            categories = [c for c in categories if c != "rag"]
        else:
            print(f"  Documents ingested: {doc_count} — RAG tests enabled")

    # Load datasets
    print("\nLoading test cases...")
    cases = load_datasets(categories)
    if not cases:
        print("No test cases found. Check datasets/eval/ directory.")
        sys.exit(1)

    print(f"\nRunning {len(cases)} test cases against {len(models)} model(s)...")
    judge_model = args.judge_model  # None means "use the model being tested"

    # Run evaluation
    # If no explicit judge model, each model judges itself (fair comparison).
    # For cross-model consistency, set --judge-model to a specific model.
    if judge_model:
        print(f"Judge model: {judge_model}")
        results = run_eval(gateway_url, models, cases, judge_model)
    else:
        print("Judge: each model judges itself (set --judge-model for cross-model consistency)")
        results = {}
        for model in models:
            single = run_eval(gateway_url, [model], cases, model)
            results.update(single)

    # Report
    print_comparison(results)

    if args.output:
        save_results(results, args.output)

    print("\nDone.")


if __name__ == "__main__":
    main()
