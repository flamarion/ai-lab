# AI Lab – Usage Guide

## Chatting with LLMs

Open http://chat.lab.local in your browser.

- **Model selection** – use the dropdown at the top of the chat window to switch between any models you have pulled into Ollama.
- **New conversation** – click the **+** icon in the left sidebar.
- **Multi-user** – multiple users can create accounts. The first account becomes the admin.

---

## Calling the Ollama API directly

The Ollama REST API is available at `http://ollama.lab.local` (port 80 via Traefik) or `http://<host-ip>:11434` directly.

### Generate a completion

```bash
curl http://ollama.lab.local/api/generate \
  -d '{
    "model": "llama3.2:3b",
    "prompt": "Why is the sky blue?",
    "stream": false
  }'
```

### Chat completion (OpenAI-compatible)

```bash
curl http://ollama.lab.local/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:3b",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

See the [Ollama API reference](https://github.com/ollama/ollama/blob/main/docs/api.md) for all endpoints.

---

## Object storage (MinIO)

### Web console

Open http://minio-console.lab.local and log in with the credentials you set in `.env` (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`).

### S3-compatible client (AWS CLI)

```bash
# Configure a profile
aws configure --profile ai-lab
# AWS Access Key ID: <MINIO_ROOT_USER>
# AWS Secret Access Key: <MINIO_ROOT_PASSWORD>
# Default region: us-east-1

# Create a bucket
aws --profile ai-lab \
    --endpoint-url http://minio.lab.local \
    s3 mb s3://my-models

# Upload a file
aws --profile ai-lab \
    --endpoint-url http://minio.lab.local \
    s3 cp ./model.gguf s3://my-models/

# List bucket contents
aws --profile ai-lab \
    --endpoint-url http://minio.lab.local \
    s3 ls s3://my-models
```

### Python (boto3)

```python
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url="http://minio.lab.local",
    aws_access_key_id="minioadmin",
    aws_secret_access_key="your-password",
    region_name="us-east-1",
)

# List buckets
for bucket in s3.list_buckets()["Buckets"]:
    print(bucket["Name"])
```

---

## Monitoring

### Grafana dashboards

Open http://grafana.lab.local and log in with the admin credentials from `.env`.

The pre-built **AI Lab Overview** dashboard shows:
- Host CPU, memory, and disk usage
- Network I/O
- Per-container CPU and memory usage

### Prometheus queries

Open http://prometheus.lab.local/graph to run ad-hoc PromQL queries.

Useful queries:

```promql
# Current CPU usage %
100 - (avg(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Memory usage %
100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))

# Container memory (bytes) grouped by container name
container_memory_usage_bytes{name!=""}
```

---

## Adding a new service

1. Add a new service block to `docker-compose.yml`.
2. Attach it to the `ai-lab` network.
3. Add Traefik labels to expose it via a hostname:
   ```yaml
   labels:
     - "traefik.enable=true"
     - "traefik.http.routers.myservice.rule=Host(`myservice.lab.local`)"
     - "traefik.http.routers.myservice.entrypoints=web"
     - "traefik.http.services.myservice.loadbalancer.server.port=<port>"
   ```
4. Add the hostname to `/etc/hosts` on all client machines.
5. Run `./scripts/start.sh` — Traefik picks up changes without a restart.

---

## Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f ollama
docker compose logs -f open-webui
```

---

## Updating individual services

```bash
# Pull latest image and restart a single service
docker compose pull ollama && docker compose up -d ollama
```
