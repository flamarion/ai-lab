#!/usr/bin/env bash
# stop.sh – Stop the AI Lab platform
# Usage: ./scripts/stop.sh [--destroy]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "\033[0;34m[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }

# ── Parse arguments ───────────────────────────────────────────────────────────
DESTROY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destroy) DESTROY=true; shift ;;
    *)         echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Confirm destructive action ────────────────────────────────────────────────
if [[ "${DESTROY}" == true ]]; then
  echo -e "${RED}${BOLD}WARNING: --destroy will remove all containers AND volumes (all data will be lost).${RESET}"
  read -r -p "Are you sure? [y/N] " confirm
  if [[ "${confirm,,}" != "y" ]]; then
    echo "Aborted."
    exit 0
  fi
fi

# ── Stop services ─────────────────────────────────────────────────────────────
if [[ "${DESTROY}" == true ]]; then
  info "Stopping and removing all containers and volumes..."
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down -v
  success "All containers and volumes removed."
else
  info "Stopping AI Lab services (data volumes preserved)..."
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" down
  success "Services stopped. Run ./scripts/start.sh to restart."
fi
