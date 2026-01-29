### Build frontend (React + TanStack)
FROM node:20-alpine AS frontend

WORKDIR /app/web
RUN corepack enable
COPY web/package.json ./
RUN pnpm install --no-frozen-lockfile
COPY web/ ./
RUN pnpm build


### Backend (FastAPI)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip uv

COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

COPY api ./api
COPY agent ./agent
COPY docs ./docs

# Copy the built UI into the expected location (served by api/app/main.py)
COPY --from=frontend /app/web/dist ./web/dist

EXPOSE 8080

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
