# Security

This is the extended security doc for **EdgeWatch Telemetry**.

If you want the short version, see the top-level `SECURITY.md`.

## Threat model (practical)

### What we assume

- Edge nodes are deployed in environments where you may not fully control physical access.
- Connectivity can be intermittent (cellular, remote Wi‑Fi).
- The system may be exposed publicly (demo posture) or be private behind IAM/IAP (common operator posture).

### Primary risks

- **Token theft** (device token or admin credentials) leading to:
  - fake telemetry injection
  - device impersonation
  - unauthorized provisioning
- **Abuse/DoS** when exposed publicly:
  - oversized payloads
  - high-rate ingest
  - extremely large “points per request” batches
- **Sensitive data leakage** in logs or exports

## Authentication + authorization

### Device authentication

- Devices authenticate to the API using a **Bearer token**.
- The API stores a **hashed token** (PBKDF2), never the raw token.

Operational guidance:

- Treat device tokens like passwords.
- Rotate tokens when a device is decommissioned or suspected compromised.

### Admin surface + admin authentication

Admin endpoints are optional and configurable.

#### Enable/disable admin routes

- `ENABLE_ADMIN_ROUTES=1` mounts `/api/v1/admin/*`
- `ENABLE_ADMIN_ROUTES=0` **removes** the admin router entirely

This enables a production “public ingest” service posture that does not expose admin routes.

#### Admin auth mode

- `ADMIN_AUTH_MODE=key` (default)
  - Admin endpoints require `X-Admin-Key`.
  - In `APP_ENV != dev`, the server **requires** `ADMIN_API_KEY` (startup fails if missing).

- `ADMIN_AUTH_MODE=none`
  - Admin endpoints do **not** require an admin key.
  - Intended for deployments protected by an infrastructure perimeter (Cloud Run IAM, IAP, VPN).

- `IAP_AUTH_ENABLED=1`
  - Admin endpoints require `X-Goog-Authenticated-User-Email`.
  - Enables defense-in-depth for IAP-protected admin services by rejecting requests without an authenticated IAP identity header.

Recommended production guidance:

- Prefer **identity-based perimeters** (Cloud Run IAM / IAP) for admin operations.
- Do not ship shared admin secrets to browsers.
- Consider splitting into multiple services (Posture C in `docs/PRODUCTION_POSTURE.md`) using route surface toggles:
  - **public ingest**: `ENABLE_UI=0`, `ENABLE_READ_ROUTES=0`, `ENABLE_INGEST_ROUTES=1`, `ENABLE_ADMIN_ROUTES=0`
  - **private dashboard** (optional, least privilege): `ENABLE_UI=1`, `ENABLE_READ_ROUTES=1`, `ENABLE_INGEST_ROUTES=0`, `ENABLE_ADMIN_ROUTES=0`
  - **private admin**: `ENABLE_UI=1`, `ENABLE_READ_ROUTES=1`, `ENABLE_INGEST_ROUTES=0`, `ENABLE_ADMIN_ROUTES=1`, `ADMIN_AUTH_MODE=none`

Admin mutations (`POST /api/v1/admin/devices`, `PATCH /api/v1/admin/devices/{device_id}`) are persisted to `admin_events` with:
- `actor_email`
- action (`device.create` / `device.update`)
- target device and request correlation id

The API also emits structured `admin_event` logs for centralized audit trails.

## Defense-in-depth controls

### 1) Payload size limiting

The API applies a request body limit (`MAX_REQUEST_BODY_BYTES`) for write endpoints:

- `/api/v1/ingest`
- `/api/v1/internal/pubsub/push`
- `/api/v1/admin/*`

This reduces risk from accidental or malicious oversized JSON requests.

### 2) Points-per-request limiting

Even if a JSON body is under the byte limit, it can contain a very large list of points.

- `MAX_POINTS_PER_REQUEST` caps `len(points)` for `/api/v1/ingest`.

This protects database write performance and reduces tail latency under abuse.

### 3) In-app rate limiting

The API includes a lightweight **token bucket limiter** for ingest:

- keyed by `device_id`
- measured in **points per minute** (`INGEST_RATE_LIMIT_POINTS_PER_MIN`)

This is a backstop. For a real internet-exposed service, prefer:

- API Gateway quotas
- Cloud Armor rate limiting
- Load balancer WAF policies

### 4) Error hygiene

- All error responses include an `X-Request-ID` header.
- Error envelopes include a `request_id` field to support log correlation.

### 5) Secrets management

Terraform supports Google Secret Manager for:

- `DATABASE_URL`
- `ADMIN_API_KEY`

Recommendations:

- Use **least privilege** service accounts.
- Rotate secrets periodically and on incident.
- Avoid placing secrets in `.env` for shared environments.

### 6) Transport security

- In production, use HTTPS only (Cloud Run manages TLS).
- Never send device/admin tokens over plaintext HTTP outside localhost.

## Production posture recommendations

See `docs/PRODUCTION_POSTURE.md` for profiles.

High-value controls for production deployments:

- Put admin operations behind an identity perimeter (Cloud Run IAM / IAP).
- Keep ingest public only if you must (IoT fleets), and add WAF + rate limits.
- Enable Cloud SQL backups and test restores.
- Use structured logging (`LOG_FORMAT=json`) and set log retention.

## Incident response quick steps

- If a device token is suspected compromised:
  1) rotate token (admin UI)
  2) mark device disabled (if needed)
  3) review recent ingests for that device

- If an admin key is suspected compromised (ADMIN_AUTH_MODE=key):
  1) rotate secret in Secret Manager
  2) redeploy
  3) review admin audit logs (Cloud Logging)

## Follow-on upgrades

Tracked work items:

- Authn/authz upgrade plan: `docs/TASKS/15-authn-authz.md`
- OpenTelemetry tracing plan: `docs/TASKS/16-opentelemetry.md`
