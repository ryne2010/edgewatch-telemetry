### Build frontend (React + TanStack)
FROM node:20-alpine AS frontend

WORKDIR /app
RUN corepack enable

# Workspace install for reproducibility + caching.
COPY package.json pnpm-workspace.yaml ./
COPY web/package.json ./web/package.json

# If you commit pnpm-lock.yaml, switch to: pnpm install --frozen-lockfile
RUN pnpm install --no-frozen-lockfile

COPY web/ ./web/
RUN pnpm -C web build


### Backend (FastAPI)
FROM python:3.11-slim

# Install uv by copying the binaries from the official distroless image.
# See: https://docs.astral.sh/uv/guides/integration/docker/
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_DEV=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install runtime deps (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# App source
COPY api ./api
COPY contracts ./contracts

# Alembic migrations
COPY alembic.ini ./
COPY migrations ./migrations

# Install the project itself (kept in a separate layer so dep-only changes cache well)
RUN uv sync --locked

# Copy the built UI into the expected location (served by api/app/main.py)
COPY --from=frontend /app/web/dist ./web/dist

# Drop privileges (Cloud Run compatible)
RUN useradd -m -u 10001 app && chown -R app:app /app
USER app

EXPOSE 8080

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
