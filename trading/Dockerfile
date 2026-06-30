# syntax=docker/dockerfile:1.7
# =======================================================================
# Vibe-Trading Docker image
# Multi-stage: build React frontend, then run Python backend
#
# Multi-arch support (linux/amd64, linux/arm64) for Oracle Cloud free tier
# (Ampere A1). Build with:
#   docker buildx create --name multi --use
#   docker buildx build --platform linux/amd64,linux/arm64 -t trade-v1:v1 .
# =======================================================================

# -------- Stage 1: Build frontend -------------------------------------
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY frontend/ ./
RUN npm run build

# -------- Stage 2: Python runtime -------------------------------------
FROM python:3.11-slim AS runtime
WORKDIR /app

# System deps for python-okx wheels + scientific libs
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Vibe-Trading + extras
# Pin the version for reproducibility
ARG VT_VERSION=0.1.10
RUN pip install --no-cache-dir \
        "vibe-trading-ai[deepseek]==${VT_VERSION}" \
        "python-okx" \
        "yfinance" \
        "pandas" \
        "numpy"

# Copy custom scripts (F1 brackets, F2 confluence, F3 regime, auto-trader)
COPY brackets/ /app/brackets/
COPY confluence/ /app/confluence/
COPY regime/ /app/regime/
COPY auto/ /app/auto/
COPY llm/ /app/llm/
COPY verifier/ /app/verifier/
COPY risk/ /app/risk/
COPY replay/ /app/replay/
COPY execution/ /app/execution/
COPY schemas/ /app/schemas/
COPY rulebook/ /app/rulebook/
COPY scripts/ /app/scripts/

# Make auto a package by adding __init__.py
RUN touch /app/auto/__init__.py

# Copy built frontend dist
# api_server.py resolves: Path(__file__).parent.parent / "frontend" / "dist"
# In the installed package at site-packages/api_server.py, that resolves to:
#   /usr/local/lib/python3.11/frontend/dist  (one level up from site-packages)
COPY --from=frontend-builder /build/dist /usr/local/lib/python3.11/frontend/dist

# Phase B-multi: override pip-installed api_server.py with our local version
# (adds /trader route for auto-trader dashboard inside Vibe-Trading UI)
COPY api_server.py /usr/local/lib/python3.11/site-packages/api_server.py
COPY berkshire_routes.py /app/berkshire_routes.py

# Persistent data directory
RUN mkdir -p /data
VOLUME ["/data"]
ENV VIBE_TRADING_HOME=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# Health check via /health endpoint (Vibe-Trading on 8000)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# Expose only port 8000 (single-port architecture)
#   /              - Vibe-Trading UI
#   /trader        - Auto-trader dashboard
#   /api/trader/*  - Auto-trader REST API
EXPOSE 8000

# Unified: single container runs Vibe-Trading UI + auto-trader + dashboard at /trader
CMD ["python", "-m", "auto.auto"]
