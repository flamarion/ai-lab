FROM python:3.12-slim

WORKDIR /app

# Node.js for npm-based MCP servers (npx, community packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Context is repo root (set in docker-compose.yml)
COPY services/llm-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/python /app/shared/python
COPY services/llm-gateway/src /app/src
COPY services/llm-gateway/mcp_servers.json /app/mcp_servers.json
COPY infra/migrations /app/infra/migrations

ENV PYTHONPATH=/app:/app/shared/python

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
