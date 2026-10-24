# crowD: web apps built with Node, served together with the API by one Python process.
FROM node:22-slim AS web
WORKDIR /build/viz
COPY viz/package.json viz/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY viz/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 \
    CROWD_ROOT=/app CROWD_STATIC=/app/viz/dist PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
COPY core core
COPY sim sim
COPY connectors connectors
COPY server server
COPY schemas schemas
RUN uv sync --frozen --no-dev --all-packages
COPY venues venues
COPY scenarios scenarios
COPY --from=web /build/viz/dist viz/dist
RUN mkdir -p venues/user runs
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "crowd_server", "--host", "0.0.0.0", "--port", "8000"]
