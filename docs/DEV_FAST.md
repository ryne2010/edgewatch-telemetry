# Fast dev loop

This is the fastest path to a tight edit → run → verify cycle.

## Prereqs

- macOS (target: M2 Max MacBook Pro)
- Docker Desktop
- `uv` (Python tooling)
- `node` + `pnpm`

See `docs/DEV_MAC.md` for full install notes.

## Setup

```bash
# Python deps (uses uv.lock)
uv sync --locked

# Node deps
corepack enable
pnpm install --frozen-lockfile
```

Or use the Makefile wrapper for Node deps:

```bash
make web-install
```

If you change Python or web dependencies, update lockfiles:

```bash
make lock
```

## Run stack

```bash
make up
```

This boots the **Docker Compose lane**:
- Postgres on `localhost:5435`
- API (+ built UI) on `http://localhost:8082`

If you want the fastest edit → reload loop, use the **host dev lane** instead:

```bash
# Start only the DB container
make db-up

# Run the API on the host with hot reload (http://localhost:8080)
make api-dev
```

In a second terminal:

```bash
# Run the UI dev server (http://localhost:5173)
make web-dev
```

## Simulate a field device

```bash
make simulate
```

If you’re running the API in the **host dev lane** (port `8080`), override the simulator’s API URL:

```bash
EDGEWATCH_API_URL=http://localhost:8080 make simulate
```

## Tight inner loop

- API code: hot reload via `make api-dev` (host dev lane)
- UI: Vite dev server via `make web-dev` (host dev lane)

## Quality gates

Run the same checks CI runs:

```bash
make harness
```
