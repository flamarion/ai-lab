#!/usr/bin/env bash
# start.sh – Start the AI Lab platform
# Usage: ./scripts/start.sh [--pull] [--model <model-name>]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.yml"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "\033[0;31m[ERROR]${RESET} $*" >&2; }

# ── Parse arguments ───────────────────────────────────────────────────────────
PULL=false
MODEL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull)   PULL=true; shift ;;
    --model)  MODEL="$2"; shift 2 ;;
    *)        echo "Unknown option: $1"; exit 1 ;;
  esac
done

# ── Validate .env ─────────────────────────────────────────────────────────────
if [[ ! -f "${ENV_FILE}" ]]; then
  warn ".env not found. Run ./scripts/setup.sh first."
  exit 1
fi

# ── Pull images if requested ──────────────────────────────────────────────────
if [[ "${PULL}" == true ]]; then
  info "Pulling latest images..."
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull
fi

# ── Start services ────────────────────────────────────────────────────────────
info "Starting AI Lab services..."
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d

# ── Wait for Ollama and pull model ────────────────────────────────────────────
if [[ -n "${MODEL}" ]]; then
  info "Waiting for Ollama to become ready..."
  ready=false
  for i in {1..30}; do
    if docker exec ollama ollama list &>/dev/null; then
      ready=true
      break
    fi
    sleep 2
    echo -n "."
  done
  echo

  if [[ "${ready}" != true ]]; then
    error "Ollama did not become ready in time. Check: docker compose logs ollama"
    exit 1
  fi

  info "Pulling model: ${MODEL}"
  docker exec ollama ollama pull "${MODEL}"
  success "Model '${MODEL}' ready."
fi

# ── Print service URLs ────────────────────────────────────────────────────────
# shellcheck source=../.env
source "${ENV_FILE}" 2>/dev/null || true

echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║              AI Lab – Services Running                   ║${RESET}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Service" "URL"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${RESET}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Chat Interface"   "http://${OPEN_WEBUI_HOST:-chat.lab.local}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Ollama API"       "http://${OLLAMA_HOST:-ollama.lab.local}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "MinIO Console"    "http://${MINIO_CONSOLE_HOST:-minio-console.lab.local}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Grafana"          "http://${GRAFANA_HOST:-grafana.lab.local}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Prometheus"       "http://${PROMETHEUS_HOST:-prometheus.lab.local}"
printf "${BOLD}║${RESET}  %-24s  %-30s ${BOLD}║${RESET}\n" "Traefik Dashboard" "http://${TRAEFIK_HOST:-traefik.lab.local}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo

success "AI Lab is up and running!"
