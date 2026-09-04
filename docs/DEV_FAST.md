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
make doctor
make setup
```

`make setup` creates missing local environment files without overwriting existing values and installs the locked dependencies. The underlying package-manager commands remain available for troubleshooting.

For UI dependencies only:

```bash
make web-install
```

If you change Python or web dependencies, update lockfiles:

```bash
make lock
```

## Run stack

```bash
make run
```

This boots the **Docker Compose lane**:
- Postgres on `localhost:5435`
- API (+ built UI) on `http://localhost:8082`

`make up` remains a compatibility alias for `make run`.

If you want the fastest edit → reload loop, use the **host dev lane** instead:

```bash
make dev
```

This starts DB + API hot reload + Vite + simulator in one command.

Manual equivalent:

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

Useful flags:

```bash
DEV_START_SIMULATE=0 make dev
DEV_STOP_DB_ON_EXIT=1 make dev
DEV_BOOTSTRAP_DEMO_DEVICE=0 make dev
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
make check
```

`make check` is non-mutating. Use `make logs` to inspect the Compose lane, `make stop` to stop it (`make down` is a compatibility alias), and `make help` to discover advanced targets.
