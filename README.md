# AI Lab 🤖

> Build your own **mini AI platform from scratch** — running entirely in your home lab.

AI Lab is a self-hosted AI platform you can spin up on any machine with Docker.  
It gives you a full-featured chat interface, a local LLM server, S3-compatible object storage, and a monitoring stack — all routed through a single reverse proxy and configured in minutes.

---

## What's included

| Service | Purpose | URL |
|---------|---------|-----|
| **[Open WebUI](https://github.com/open-webui/open-webui)** | ChatGPT-style chat interface | `http://chat.lab.local` |
| **[Ollama](https://ollama.com)** | Local LLM server (llama3, mistral, phi3, …) | `http://ollama.lab.local` |
| **[MinIO](https://min.io)** | S3-compatible object storage | `http://minio-console.lab.local` |
| **[Grafana](https://grafana.com)** | Dashboards & visualisation | `http://grafana.lab.local` |
| **[Prometheus](https://prometheus.io)** | Metrics collection | `http://prometheus.lab.local` |
| **[Traefik](https://traefik.io)** | Reverse proxy + router | `http://traefik.lab.local` |

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/flamarion/ai-lab.git
cd ai-lab

# 2. One-time setup (creates .env, pulls images)
./scripts/setup.sh

# 3. Edit passwords in .env, then add /etc/hosts entries (setup.sh prints them)

# 4. Start everything + pull a first model
./scripts/start.sh --model llama3.2:3b

# 5. Open the chat UI
open http://chat.lab.local
```

See [docs/setup.md](docs/setup.md) for the full setup guide.

---

## Requirements

- Docker 24+ with the Compose plugin (`docker compose`)
- 8 GB RAM minimum (16 GB recommended for larger models)
- 40 GB free disk space (SSD recommended)
- Linux x86_64 host (macOS / WSL2 also work)

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/setup.md](docs/setup.md) | Step-by-step installation and configuration |
| [docs/usage.md](docs/usage.md) | How to chat, use the API, manage models, and use MinIO |
| [docs/architecture.md](docs/architecture.md) | Component diagram and design decisions |

---

## Managing the platform

```bash
# Start (with optional image update)
./scripts/start.sh [--pull] [--model <model-name>]

# Stop (keeps all data)
./scripts/stop.sh

# Stop and wipe all data
./scripts/stop.sh --destroy
```

---

## GPU acceleration

Ollama supports NVIDIA GPUs.  Uncomment the `deploy` block in the `ollama` service inside `docker-compose.yml` and install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).  See [docs/setup.md#gpu-support](docs/setup.md#gpu-support) for details.

---

## License

[Apache 2.0](LICENSE)