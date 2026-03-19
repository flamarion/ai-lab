#!/usr/bin/env python3
"""Ingest documents into the RAG pipeline via the gateway API.

Usage:
    python scripts/ingest.py <file_or_directory> [--gateway URL]

Examples:
    python scripts/ingest.py docs/my-notes.md
    python scripts/ingest.py docs/                     # all supported files in directory
    python scripts/ingest.py report.pdf --gateway http://192.168.1.100:8000
"""

import argparse
import sys
from pathlib import Path

import httpx

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".rst", ".csv", ".log",
    ".py", ".js", ".ts", ".go", ".rs", ".rb", ".java", ".kt",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".css",
    ".sql", ".tf", ".hcl",
    ".pdf",
}


def ingest_file(filepath: Path, gateway_url: str) -> dict | None:
    """Upload a single file to the gateway /ingest endpoint."""
    try:
        with open(filepath, "rb") as f:
            resp = httpx.post(
                f"{gateway_url}/ingest",
                files={"file": (filepath.name, f)},
                timeout=120.0,
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        print(f"  ERROR: {e.response.status_code} — {e.response.text}")
        return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def collect_files(path: Path) -> list[Path]:
    """Collect supported files from a path (file or directory)."""
    if path.is_file():
        if path.suffix.lower() in SUPPORTED_EXTENSIONS or path.name == "Dockerfile":
            return [path]
        print(f"Unsupported file type: {path.suffix}")
        return []

    if path.is_dir():
        files = []
        for f in sorted(path.rglob("*")):
            if f.is_file() and (f.suffix.lower() in SUPPORTED_EXTENSIONS or f.name == "Dockerfile"):
                files.append(f)
        return files

    print(f"Path not found: {path}")
    return []


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into AI Lab RAG pipeline")
    parser.add_argument("path", help="File or directory to ingest")
    parser.add_argument("--gateway", default="http://localhost:8000", help="Gateway URL")
    args = parser.parse_args()

    target = Path(args.path)
    files = collect_files(target)

    if not files:
        print("No supported files found.")
        sys.exit(1)

    print(f"Found {len(files)} file(s) to ingest\n")

    success = 0
    total_chunks = 0

    for filepath in files:
        print(f"  {filepath.name} ... ", end="", flush=True)
        result = ingest_file(filepath, args.gateway)
        if result:
            n = result["num_chunks"]
            total_chunks += n
            success += 1
            print(f"OK ({n} chunks)")
        else:
            print("FAILED")

    print(f"\nDone: {success}/{len(files)} files ingested, {total_chunks} total chunks")


if __name__ == "__main__":
    main()
