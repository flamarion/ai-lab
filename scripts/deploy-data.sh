#!/usr/bin/env bash
# Deploy data services on the ai-data VM (homelab)
# Usage: ./scripts/deploy-data.sh [--down] [--status] [--logs]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/docker"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.data.yml"

get_lan_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' || echo "<ai-data-vm-ip>"
}

# --- Flag handling ---

case "${1:-}" in
    --down)
        echo "Stopping data services..."
        cd "$COMPOSE_DIR"
        docker compose -f docker-compose.data.yml down
        exit 0
        ;;
    --status)
        cd "$COMPOSE_DIR"
        docker compose -f docker-compose.data.yml ps
        exit 0
        ;;
    --logs)
        cd "$COMPOSE_DIR"
        shift
        docker compose -f docker-compose.data.yml logs "$@"
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
echo "Starting data services..."
cd "$COMPOSE_DIR"
docker compose -f docker-compose.data.yml up --build -d

# --- Show access info ---

LAN_IP=$(get_lan_ip)
echo ""
echo "=== Data services deployed ==="
echo "Postgres:  ${LAN_IP}:5432  (db: ailab, user: ailab)"
echo ""
echo "Useful commands:"
echo "  ./scripts/deploy-data.sh --status   Show container status"
echo "  ./scripts/deploy-data.sh --logs     Tail all logs"
echo "  ./scripts/deploy-data.sh --logs -f  Follow logs"
echo "  ./scripts/deploy-data.sh --down     Stop data services"
