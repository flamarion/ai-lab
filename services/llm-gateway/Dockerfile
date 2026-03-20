FROM python:3.12-slim

WORKDIR /app

# Context is repo root (set in docker-compose.yml)
COPY services/llm-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/python /app/shared/python
COPY services/llm-gateway/src /app/src
COPY services/llm-gateway/mcp_servers.json /app/mcp_servers.json
COPY infra/migrations /app/infra/migrations

ENV PYTHONPATH=/app:/app/shared/python

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
