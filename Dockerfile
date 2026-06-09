# Stage 1: Build React frontend
FROM node:20-slim AS frontend
WORKDIR /app/testmcpy/ui
COPY testmcpy/ui/package*.json ./
RUN npm ci --no-audit --no-fund
COPY testmcpy/ui/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Optionally bake the Claude Code CLI into the image so `docker exec
# <container> claude` works without a per-container install (SC-108437).
#
# Gated behind two build ARGs so the default published image stays
# lean — the CLI is only useful for users who want in-container agent
# workflows. Opt in with:
#
#     docker compose build --build-arg INSTALL_CLAUDE_CLI=true
#
# Pin a specific version for reproducibility (recommended for shared
# images — install.sh otherwise floats `latest` and the same source
# SHA can produce different binaries weeks apart):
#
#     docker compose build \
#         --build-arg INSTALL_CLAUDE_CLI=true \
#         --build-arg CLAUDE_CLI_VERSION=2.1.170
#
# Trust model: this image pipes the install script from claude.ai
# directly into a shell — `curl … | bash`. There's no upstream
# checksum / signature for the standalone installer to pin against
# today. Acceptable for an opt-in dev image built by the user that
# already runs as root inside the container; not appropriate for a
# zero-trust supply chain. Pin the version above so the surface a
# compromised installer could affect is bounded.
#
# We use the native installer because the slim base has no Node.js;
# `npm install -g @anthropic-ai/claude-code` would pull the entire
# Node toolchain. The installer drops the binary at
# /root/.local/bin/claude which isn't on the default `docker exec`
# PATH — symlink to /usr/local/bin/claude so it's discoverable. Layer
# is placed right after curl so it shares the cache with the apt-get
# step and is NOT invalidated by source changes below.
#
# `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` makes `curl | bash`
# fail the build if curl itself fails (default `/bin/sh -c` uses the
# pipeline tail's exit status; a 5xx from claude.ai would otherwise
# let curl fail silently and the build proceed to a dangling symlink).
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG INSTALL_CLAUDE_CLI=false
ARG CLAUDE_CLI_VERSION=""
RUN if [ "$INSTALL_CLAUDE_CLI" = "true" ]; then \
        curl -fsSL https://claude.ai/install.sh | bash && \
        if [ -n "$CLAUDE_CLI_VERSION" ]; then \
            /root/.local/bin/claude install "$CLAUDE_CLI_VERSION"; \
        fi && \
        ln -sf /root/.local/bin/claude /usr/local/bin/claude && \
        claude --version; \
    fi

# Install Python dependencies
COPY pyproject.toml .
COPY testmcpy/ testmcpy/
# Copy built frontend before pip install so it's included in package data
COPY --from=frontend /app/testmcpy/ui/dist testmcpy/ui/dist
RUN pip install --no-cache-dir ".[server]"

# Create data directory for persistent storage
RUN mkdir -p /app/.testmcpy

# Default environment variables
ENV TESTMCPY_DB_PATH=/app/.testmcpy/storage.db

# Volume for persistent data (database, configs)
VOLUME /app/.testmcpy

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["testmcpy", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
