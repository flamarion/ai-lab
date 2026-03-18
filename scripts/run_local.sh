#!/usr/bin/env bash
# Run the full stack locally with Docker Compose
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check for .env
if [ ! -f "$REPO_ROOT/.env" ]; then
    echo "Error: .env file not found. Copy .env.example to .env and fill in your values:"
    echo "  cp .env.example .env"
    exit 1
fi

cd "$REPO_ROOT/infra/docker"
docker compose up --build "$@"
