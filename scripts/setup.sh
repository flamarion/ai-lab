#!/usr/bin/env bash
# setup.sh – One-time setup for the AI Lab platform
# Usage: ./scripts/setup.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
ENV_EXAMPLE="${REPO_ROOT}/.env.example"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }

# ── Check prerequisites ───────────────────────────────────────────────────────
check_prerequisites() {
  info "Checking prerequisites..."
  local missing=()

  for cmd in docker curl openssl; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done

  if ! docker compose version &>/dev/null 2>&1; then
    missing+=("docker compose (plugin)")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    error "Missing required tools: ${missing[*]}"
    echo "Please install them and re-run this script."
    exit 1
  fi

  success "All prerequisites found."
}

# ── Create .env file ──────────────────────────────────────────────────────────
create_env_file() {
  if [[ -f "${ENV_FILE}" ]]; then
    warn ".env file already exists. Skipping creation."
    return
  fi

  info "Creating .env from .env.example..."
  cp "${ENV_EXAMPLE}" "${ENV_FILE}"

  # Generate a random secret for WEBUI_SECRET_KEY
  local secret
  secret=$(openssl rand -hex 32)
  # Use portable sed that works on both Linux and macOS
  sed -i.bak "s|change-me-use-openssl-rand-hex-32|${secret}|g" "${ENV_FILE}" && rm -f "${ENV_FILE}.bak"

  warn "IMPORTANT: Edit ${ENV_FILE} and update all passwords before starting."
  warn "  - MINIO_ROOT_PASSWORD"
  warn "  - GF_SECURITY_ADMIN_PASSWORD"
  warn "  - LAB_HOST_IP (set to your host machine's IP)"
  success ".env file created."
}

# ── Print /etc/hosts entries ──────────────────────────────────────────────────
print_hosts_hint() {
  # shellcheck source=../.env
  source "${ENV_FILE}" 2>/dev/null || true
  local ip="${LAB_HOST_IP:-127.0.0.1}"

  echo
  echo -e "${BOLD}Add the following lines to /etc/hosts on every machine that needs access:${RESET}"
  echo -e "${YELLOW}"
  echo "${ip}  ${TRAEFIK_HOST:-traefik.lab.local}"
  echo "${ip}  ${OLLAMA_HOST:-ollama.lab.local}"
  echo "${ip}  ${OPEN_WEBUI_HOST:-chat.lab.local}"
  echo "${ip}  ${MINIO_HOST:-minio.lab.local}"
  echo "${ip}  ${MINIO_CONSOLE_HOST:-minio-console.lab.local}"
  echo "${ip}  ${PROMETHEUS_HOST:-prometheus.lab.local}"
  echo "${ip}  ${GRAFANA_HOST:-grafana.lab.local}"
  echo -e "${RESET}"
}

# ── Pull images ───────────────────────────────────────────────────────────────
pull_images() {
  info "Pulling Docker images (this may take a while)..."
  docker compose --env-file "${ENV_FILE}" -f "${REPO_ROOT}/docker-compose.yml" pull
  success "Images pulled."
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo
  echo -e "${BOLD}╔══════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║        AI Lab – Setup Script         ║${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════╝${RESET}"
  echo

  check_prerequisites
  create_env_file
  pull_images
  print_hosts_hint

  echo
  success "Setup complete! Run ${BOLD}./scripts/start.sh${RESET} to launch the platform."
}

main "$@"
