#!/usr/bin/env bash
# Deploy the full stack on the ai-app VM (homelab)
# Usage: ./scripts/deploy.sh [--down] [--status] [--logs] [--build-only]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/docker"

# Detect the VM's LAN IP for display purposes
get_lan_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' || echo "<ai-app-vm-ip>"
}

# --- Flag handling ---

case "${1:-}" in
    --down)
        echo "Stopping all services..."
        cd "$COMPOSE_DIR"
        docker compose down
        exit 0
        ;;
    --status)
        cd "$COMPOSE_DIR"
        docker compose ps
        exit 0
        ;;
    --logs)
        cd "$COMPOSE_DIR"
        shift
        docker compose logs "$@"
        exit 0
        ;;
    --build-only)
        cd "$COMPOSE_DIR"
        docker compose build
        exit 0
        ;;
esac

# --- Pre-flight checks ---

if [ ! -f "$REPO_ROOT/.env" ]; then
    echo "Error: .env file not found. Copy .env.example to .env and fill in your values:"
    echo "  cp .env.example .env"
    exit 1
fi

# Pull latest changes (fast-forward only to avoid accidental merges)
echo "Pulling latest changes..."
cd "$REPO_ROOT"
git pull --ff-only

# Build and start services (detached so containers survive SSH disconnect)
echo "Building and starting services..."
cd "$COMPOSE_DIR"
docker compose up --build -d

# --- Show access info ---

LAN_IP=$(get_lan_ip)
echo ""
echo "=== Deployment complete ==="
echo "Chat UI:       http://${LAN_IP}:8501"
echo "LLM Gateway:   http://${LAN_IP}:8000"
echo "API Docs:      http://${LAN_IP}:8000/docs"
echo ""
echo "Useful commands:"
echo "  ./scripts/deploy.sh --status   Show container status"
echo "  ./scripts/deploy.sh --logs     Tail all logs"
echo "  ./scripts/deploy.sh --logs -f  Follow logs"
echo "  ./scripts/deploy.sh --down     Stop all services"
