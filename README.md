# EdgeWatch Telemetry

**Reliable telemetry and alerting for remote equipment on unreliable networks.**

EdgeWatch is a local-first platform for monitoring pumps, wells, and other unattended equipment. An edge agent collects readings, buffers them through outages, and sends them to a FastAPI service backed by Postgres. A React console turns that data into fleet health, time-series views, and auditable alerts.

The Docker path is the supported demo. Terraform defines optional Google Cloud infrastructure; no public deployment is claimed.

> **Reliability, in code:** Failed sends enter a bounded SQLite outbox. Successful deliveries are removed only after acknowledgement, and the API deduplicates retries by `(device_id, message_id)`.

## Why it exists

Remote monitoring fails in predictable ways: connectivity drops, retries duplicate data, device payloads drift, and alerts lose their operational context. EdgeWatch treats those as data-integrity and operator-workflow problems.

| Failure mode | EdgeWatch response |
| --- | --- |
| Network loss | Durable edge buffering with bounded storage, backoff, and replay |
| Duplicate delivery | Idempotent ingest keyed by `(device_id, message_id)` |
| Payload drift | Versioned contracts, validation, quarantine, and drift history |
| Silent equipment failure | Heartbeat state, metric thresholds, and alert lifecycle tracking |
| Unclear notification behavior | Routing decisions, throttling, and delivery attempts remain auditable |

## What the core path includes

- A Python edge agent with pluggable sensors, UTC timestamps, policy caching, local buffering, and reconnect flushes.
- A FastAPI service and Postgres schema for authenticated ingest, contracts, lineage, alerts, and operational history.
- A React console for fleet health, device detail, time-series inspection, contracts, alerts, and audit views.
- Operational tooling for offline checks, retention, buffered-data replay, and analytics export, with optional Pub/Sub, BigQuery, and Cloud Run paths.

## Run locally

The Docker path requires Docker Desktop with Compose v2.

```bash
make up
```

Open <http://localhost:8082>. The stack builds the API and UI, migrates Postgres, and creates an 11-device demo fleet. API documentation is available at <http://localhost:8082/docs>.

To stream synthetic telemetry, start the simulator in another terminal:

```bash
make simulate
```

The simulator requires Python 3.11, `uv`, Node 20, and pnpm/Corepack. Use `SIMULATE_FLEET_SIZE=1 make simulate` for a single device, and `make down` when finished.

For API and UI hot reload, see the [fast development loop](docs/DEV_FAST.md). The local stack uses development credentials; keep it on a trusted machine and network.

## Design boundaries

EdgeWatch deliberately separates paths with different trust and failure models.

| Path | Purpose | Status |
| --- | --- | --- |
| API-backed edge telemetry | HTTPS ingest, Postgres history, operator UI, and alert lifecycle | Supported local demo |
| GCP deployment path | Cloud Run, managed jobs, optional Pub/Sub and BigQuery, infrastructure as code | Demonstration infrastructure; live deployment not verified |
| OTA orchestration | Staged targeting, artifact hashes, optional RSA signatures, and power guards | Feature-gated and dry-run by default; system images are not qualified |

The cloud and update paths remain opt-in. Production use requires environment-specific identity, secret management, backup testing, rollback exercises, and hardware qualification.

EdgeWatch does not target high-throughput warehousing or multi-tenant SaaS. Its scope is reliable remote-device telemetry, alerting, and bounded control.

## Security posture

- Device credentials are opaque bearer tokens; the server stores PBKDF2 hashes and non-secret fingerprints, not plaintext tokens.
- Optional device and fleet grants constrain operator access. Administrative routes can be removed entirely or protected by an infrastructure identity perimeter.
- Telemetry contracts reject or quarantine type mismatches and record drift evidence for investigation.
- Update agents default to dry-run behavior; signed artifacts are available but not mandatory.
- Secrets and raw credentials are excluded from normal logs and operator responses.

See [SECURITY.md](SECURITY.md) for reporting and baseline controls.

## Validate the repository

Run the source gate used by the project:

```bash
make harness
```

It checks Python and TypeScript linting and types, tests, and the web build. Run `make hygiene` for repository hygiene and `make tf-check` for infrastructure changes.

## Read next

- [Domain and system boundaries](docs/DOMAIN.md)
- [Architecture and design decisions](docs/DESIGN.md)
- [API and data contracts](docs/CONTRACTS.md)
- [Raspberry Pi deployment](docs/DEPLOY_RPI.md) and [hardware scope](docs/HARDWARE.md)
- [Zero-touch Raspberry Pi bootstrap](docs/TUTORIALS/RPI_ZERO_TOUCH_BOOTSTRAP.md)
- [Contributing guide](CONTRIBUTING.md)

MIT licensed. See [LICENSE](LICENSE).
