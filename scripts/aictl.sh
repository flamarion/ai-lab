#!/usr/bin/env bash
# aictl — unified control for AI Lab services
# Usage: ./scripts/aictl.sh <command> [target] [options]
#
# Commands:
#   start    Pull latest code, build, and start services
#   stop     Stop services
#   restart  Stop then start services
#   rebuild  Force rebuild images and restart services
#   status   Show container status
#   logs     Show logs (pass -f to follow)
#
# Targets:
#   app      Gateway + Chat UI (ai-app VM)
#   data     Postgres (ai-data VM)
#   all      Both (default)
#
# Examples:
#   ./scripts/aictl.sh start            # pull + start everything
#   ./scripts/aictl.sh restart app      # restart app services only
#   ./scripts/aictl.sh logs data -f     # follow data service logs
#   ./scripts/aictl.sh status           # show all container status
#   ./scripts/aictl.sh rebuild app      # force rebuild app images

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infra/docker"

# Compose files
APP_COMPOSE="docker-compose.yml"
DATA_COMPOSE="docker-compose.data.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log()  { echo -e "${CYAN}▸${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

get_lan_ip() {
    hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost"
}

usage() {
    sed -n '2,/^$/{ s/^# //; s/^#//; p }' "$0"
    exit 1
}

# --- Resolve target ---

COMMAND="${1:-}"
TARGET="${2:-all}"
shift 2 2>/dev/null || shift $# 2>/dev/null
EXTRA_ARGS=("$@")

if [ -z "$COMMAND" ]; then
    usage
fi

# Determine which compose files to operate on
run_app=false
run_data=false

case "$TARGET" in
    app)  run_app=true ;;
    data) run_data=true ;;
    all)  run_app=true; run_data=true ;;
    *)    err "Unknown target: $TARGET (use app, data, or all)"; exit 1 ;;
esac

# --- Helpers ---

compose_app()  { cd "$COMPOSE_DIR" && docker compose -f "$APP_COMPOSE" "$@"; }
compose_data() { cd "$COMPOSE_DIR" && docker compose -f "$DATA_COMPOSE" "$@"; }

check_env() {
    if [ ! -f "$REPO_ROOT/.env" ]; then
        err ".env file not found. Run: cp .env.example .env"
        exit 1
    fi
}

pull_latest() {
    log "Pulling latest code..."
    cd "$REPO_ROOT"
    git pull --ff-only
    ok "Code up to date"
}

# --- Commands ---

do_start() {
    check_env
    pull_latest

    if $run_data; then
        log "Starting data services..."
        compose_data up -d
        ok "Data services started"
    fi

    if $run_app; then
        log "Building and starting app services..."
        compose_app up --build -d
        ok "App services started"
    fi

    show_info
}

do_stop() {
    if $run_app; then
        log "Stopping app services..."
        compose_app down
        ok "App services stopped"
    fi

    if $run_data; then
        log "Stopping data services..."
        compose_data down
        ok "Data services stopped"
    fi
}

do_restart() {
    do_stop
    echo ""
    do_start
}

do_rebuild() {
    check_env
    pull_latest

    if $run_app; then
        log "Rebuilding app services (no cache)..."
        compose_app build --no-cache
        compose_app up -d
        ok "App services rebuilt and started"
    fi

    if $run_data; then
        log "Rebuilding data services (no cache)..."
        compose_data build --no-cache
        compose_data up -d
        ok "Data services rebuilt and started"
    fi

    show_info
}

do_status() {
    if $run_app; then
        echo -e "${BOLD}=== App Services ===${NC}"
        compose_app ps 2>/dev/null || warn "App compose not running"
        echo ""
    fi

    if $run_data; then
        echo -e "${BOLD}=== Data Services ===${NC}"
        compose_data ps 2>/dev/null || warn "Data compose not running"
    fi
}

do_logs() {
    if $run_app && $run_data; then
        warn "Showing logs for both targets — use 'app' or 'data' to filter"
        echo -e "${BOLD}=== App Logs ===${NC}"
        compose_app logs "${EXTRA_ARGS[@]}" 2>/dev/null || true
        echo -e "\n${BOLD}=== Data Logs ===${NC}"
        compose_data logs "${EXTRA_ARGS[@]}" 2>/dev/null || true
    elif $run_app; then
        compose_app logs "${EXTRA_ARGS[@]}"
    elif $run_data; then
        compose_data logs "${EXTRA_ARGS[@]}"
    fi
}

show_info() {
    LAN_IP=$(get_lan_ip)
    echo ""
    echo -e "${BOLD}=== AI Lab ===${NC}"
    if $run_app; then
        echo -e "  Chat UI:     ${GREEN}http://${LAN_IP}:8501${NC}"
        echo -e "  Gateway:     ${GREEN}http://${LAN_IP}:8000${NC}"
        echo -e "  API Docs:    ${GREEN}http://${LAN_IP}:8000/docs${NC}"
    fi
    if $run_data; then
        echo -e "  Postgres:    ${GREEN}${LAN_IP}:5432${NC}"
    fi
    echo ""
}

# --- Dispatch ---

case "$COMMAND" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_restart ;;
    rebuild) do_rebuild ;;
    status)  do_status ;;
    logs)    do_logs ;;
    *)       err "Unknown command: $COMMAND"; echo ""; usage ;;
esac
