# AI Lab – Setup Guide

## Prerequisites

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Linux (x86_64) | Ubuntu 22.04 / Debian 12 |
| RAM | 8 GB | 16 GB+ |
| Disk | 40 GB free | 100 GB+ SSD |
| Docker | 24.x | latest |
| Docker Compose plugin | v2.x | latest |
| (Optional) NVIDIA GPU | — | RTX 3060+ with CUDA 12 |

Install Docker and the Compose plugin by following the [official Docker docs](https://docs.docker.com/engine/install/).

---

## 1 – Clone the repository

```bash
git clone https://github.com/flamarion/ai-lab.git
cd ai-lab
```

---

## 2 – Run the setup script

```bash
./scripts/setup.sh
```

This will:
- Check that Docker and Docker Compose are installed
- Create a `.env` file from `.env.example` with a randomly generated `WEBUI_SECRET_KEY`
- Pull all Docker images

---

## 3 – Edit .env

Open `.env` and update at minimum:

```bash
# Choose strong passwords
MINIO_ROOT_PASSWORD=your-strong-password
GF_SECURITY_ADMIN_PASSWORD=your-grafana-password

# Set to your home lab host IP
LAB_HOST_IP=192.168.1.100
```

> ⚠️  Never commit `.env` to version control — it is already in `.gitignore`.

---

## 4 – Add /etc/hosts entries

On **every machine** that needs to access the platform (including your own laptop), add the host entries that `setup.sh` printed.  For example:

```
192.168.1.100  traefik.lab.local
192.168.1.100  chat.lab.local
192.168.1.100  ollama.lab.local
192.168.1.100  minio.lab.local
192.168.1.100  minio-console.lab.local
192.168.1.100  prometheus.lab.local
192.168.1.100  grafana.lab.local
```

On macOS/Linux: `sudo nano /etc/hosts`  
On Windows: `C:\Windows\System32\drivers\etc\hosts` (run Notepad as Administrator)

---

## 5 – Start the platform

```bash
./scripts/start.sh
```

To also pull a first LLM (e.g. Llama 3.2 3B — fast on CPU-only hardware):

```bash
./scripts/start.sh --model llama3.2:3b
```

---

## 6 – Open the services

| Service | URL |
|---------|-----|
| Chat Interface | http://chat.lab.local |
| MinIO Console | http://minio-console.lab.local |
| Grafana | http://grafana.lab.local |
| Prometheus | http://prometheus.lab.local |
| Traefik Dashboard | http://traefik.lab.local |
| Ollama API | http://ollama.lab.local |

---

## 7 – First-time Open WebUI setup

1. Open http://chat.lab.local
2. Click **Sign Up** and create the first (admin) account
3. Select your model from the dropdown (if you pulled one, it appears immediately)
4. Start chatting!

---

## 8 – Pulling more models

Use `docker exec` to run Ollama commands:

```bash
# List available models
docker exec ollama ollama list

# Pull a model  (see https://ollama.com/library for the full list)
docker exec ollama ollama pull mistral
docker exec ollama ollama pull phi3
docker exec ollama ollama pull llama3.2:3b
docker exec ollama ollama pull codellama

# Remove a model
docker exec ollama ollama rm mistral
```

---

## GPU support

If you have an NVIDIA GPU and the NVIDIA Container Toolkit installed:

1. Open `docker-compose.yml`
2. Find the `ollama` service and **uncomment** the `deploy` block:
   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: all
             capabilities: [gpu]
   ```
3. Restart Ollama: `docker compose restart ollama`

---

## Stopping the platform

```bash
# Stop containers but keep all data
./scripts/stop.sh

# Stop AND delete all data (irreversible)
./scripts/stop.sh --destroy
```

---

## Updating

```bash
./scripts/start.sh --pull
```

This pulls the latest images and restarts any containers whose image has changed.
