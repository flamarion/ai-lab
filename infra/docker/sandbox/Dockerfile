FROM python:3.12-slim

# Install Node.js 22 (matching gateway setup)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Non-root user for sandboxed execution
RUN useradd -m -s /bin/bash sandbox
USER sandbox
WORKDIR /home/sandbox
