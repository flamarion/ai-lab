# AI Lab – Architecture Overview

## High-level design

```
                        ┌─────────────────────────────────────────────────────┐
                        │                   Home Lab Host                     │
                        │                                                     │
  Browser / API Client  │  ┌──────────┐                                       │
  ──────────────────►   │  │ Traefik  │  Reverse proxy + router               │
         HTTP :80        │  │ :80/:443 │  (routes by hostname)                 │
                        │  └────┬─────┘                                       │
                        │       │ routes to service by Host header             │
                        │  ┌────┴────────────────────────────────────────┐    │
                        │  │               ai-lab Docker network          │    │
                        │  │                                              │    │
                        │  │  ┌─────────────┐   ┌──────────────────────┐ │    │
                        │  │  │   Ollama    │   │    Open WebUI        │ │    │
                        │  │  │  :11434     │◄──│  chat.lab.local      │ │    │
                        │  │  │ (LLM server)│   │  (Chat interface)    │ │    │
                        │  │  └─────────────┘   └──────────────────────┘ │    │
                        │  │                                              │    │
                        │  │  ┌─────────────┐   ┌──────────────────────┐ │    │
                        │  │  │    MinIO    │   │      Grafana         │ │    │
                        │  │  │ :9000/:9001 │   │  grafana.lab.local   │ │    │
                        │  │  │ (S3 storage)│   │  (Dashboards)        │ │    │
                        │  │  └─────────────┘   └──────────┬───────────┘ │    │
                        │  │                               │              │    │
                        │  │  ┌─────────────┐             │              │    │
                        │  │  │ Prometheus  │◄────────────┘              │    │
                        │  │  │  :9090      │  (scrapes metrics)         │    │
                        │  │  └──────┬──────┘                            │    │
                        │  │         │ scrapes                           │    │
                        │  │  ┌──────┴──────────────┐                   │    │
                        │  │  │  node-exporter       │  host metrics     │    │
                        │  │  │  cadvisor            │  container metrics│    │
                        │  │  └─────────────────────┘                   │    │
                        │  └────────────────────────────────────────────┘    │
                        └─────────────────────────────────────────────────────┘
```

## Components

| Component | Image | Role |
|-----------|-------|------|
| **Traefik** | `traefik:v3.3` | Reverse proxy — routes incoming HTTP requests to the correct service by hostname. Provides a built-in dashboard at `traefik.lab.local`. |
| **Ollama** | `ollama/ollama:latest` | LLM server — runs large language models locally. Compatible with most GGUF / Ollama-format models. Supports CPU and NVIDIA GPU. |
| **Open WebUI** | `ghcr.io/open-webui/open-webui:main` | Web chat interface — a ChatGPT-like UI that talks to the Ollama backend. Multi-user, supports model selection and conversation history. |
| **MinIO** | `minio/minio:latest` | S3-compatible object storage — stores model artefacts, datasets, and any files your AI workflows produce. |
| **Prometheus** | `prom/prometheus:latest` | Time-series metrics — scrapes metrics from all services and the host. |
| **Grafana** | `grafana/grafana:latest` | Dashboards — visualises Prometheus data. Ships with a pre-built AI Lab Overview dashboard. |
| **node-exporter** | `prom/node-exporter:latest` | Host metrics — exposes CPU, memory, disk, and network stats to Prometheus. |
| **cAdvisor** | `gcr.io/cadvisor/cadvisor:latest` | Container metrics — exposes per-container CPU, memory, and I/O stats to Prometheus. |

## Data persistence

All stateful services use named Docker volumes:

| Volume | Service | Contents |
|--------|---------|----------|
| `ollama-data` | Ollama | Downloaded model weights |
| `open-webui-data` | Open WebUI | Users, conversations, settings |
| `minio-data` | MinIO | Uploaded objects/buckets |
| `prometheus-data` | Prometheus | Metrics history (15-day retention) |
| `grafana-data` | Grafana | Dashboard changes, plugins |

Volumes survive `docker compose down` but are removed by `./scripts/stop.sh --destroy`.

## Networking

All services are attached to a single bridge network called `ai-lab`.  
Traefik reads Docker labels on each service to build routing rules automatically — no manual configuration file changes are needed when adding new services.

## GPU support

Ollama supports NVIDIA GPUs.  To enable GPU passthrough, uncomment the `deploy` block for the `ollama` service in `docker-compose.yml` and ensure the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) is installed on the host.
