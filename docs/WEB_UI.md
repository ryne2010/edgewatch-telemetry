# Web UI

The EdgeWatch UI is a single-page React app (Vite + TanStack Router/Query/Table) designed for **telemetry + ops workflows**:

- Fleet status at a glance (online/offline/unknown)
- Fleet vitals (pressure/battery/signal) driven by the **edge policy contract**
- Device drill-down with charts + raw points + oil life gauge
- Alert feed + timeline grouping + routing audit visibility
- Contract visibility (telemetry keys/types/units + edge policy cadence/thresholds)
- Admin audit lanes (events, ingestions, drift, notifications, exports)

The UI is served by the API in production (same origin), and by Vite in the fast dev lane.

## Run locally (Mac dev)

Fast host-dev lane:

```bash
make db-up
make api-dev
make web-dev
```

- UI: `http://localhost:5173`
- API: `http://localhost:8080`
- Swagger: `http://localhost:8080/docs`

Compose lane (API serves the built UI):

```bash
make up
```

- UI + API: `http://localhost:8082`

## Navigation

The left sidebar (desktop) / drawer (mobile) includes:

- **Dashboard**: fleet overview (device counts, open alerts, offline devices) + vitals threshold cards.
  - Uses `GET /api/v1/devices/summary` to avoid N+1 calls.
  - Uses `GET /api/v1/contracts/edge_policy` for thresholds.
- **Devices**: searchable fleet table with quick filters (`online/offline/unknown/open alerts`), health explanations, and latest vitals chips.
- **Alerts**: alert feed with severity/device/type/open filters, volume sparklines, grouped timeline views, and routing decision audit details (when admin notifications are enabled).
- **Contracts**: telemetry contract + edge policy contract (cadence/thresholds).
- **Admin**: audit console (only shown when the backend enables admin routes), including principal-attributed mutation events.
- **Settings**: theme + admin access configuration.
- **System**: API health + contract metadata + links to docs.

## Admin access

Admin endpoints are optional and configurable:

- `ENABLE_ADMIN_ROUTES=0` removes `/api/v1/admin/*` entirely (recommended for a public ingest service)
- `ADMIN_AUTH_MODE=key|none`
  - `key` (default): requires `X-Admin-Key` in requests
  - `none`: trusts an infrastructure perimeter (Cloud Run IAM / IAP / VPN)

The UI reads `/api/v1/health` and automatically:

- hides the Admin navigation when admin routes are disabled
- removes the “admin key required” UX when `ADMIN_AUTH_MODE=none`
- shows actionable auth guidance on admin/audit views when requests fail with `401` or `403`
  (IAP/IAM sign-in guidance for `none`, admin-key guidance for `key`)

### Using an admin key (dev/local)

If the backend is running with `ADMIN_AUTH_MODE=key`, set an admin key via environment variables (see `.env.example`) and then configure it in the UI:

1. Open **Settings**
2. Paste the admin key (must match `ADMIN_API_KEY` on the server)
3. Save

#### Storage behavior

- **Save (session)** stores the key in `sessionStorage` (cleared when the browser closes)
- **Save + persist** stores the key in `localStorage` only for localhost/dev posture

For production deployments, do **not** expose the admin key to browsers unless you also have a proper auth boundary.
Prefer Cloud Run IAM/IAP and `ADMIN_AUTH_MODE=none`, or deploy a separate private admin service.

## Device detail

The device page provides:

- **Overview**: heartbeat status + curated “latest telemetry” panel + quick chart + oil life service gauge + vitals sparklines
  - oil life panel includes the most recent reset timestamp when devices publish `oil_life_reset_at`
- **Telemetry**: metric selector + chart (numeric metrics) + raw point explorer
- **Admin tabs** (if enabled): events, ingestions, drift events, notification audits
- **Media**:
  - device-scoped media gallery (`/api/v1/devices/{device_id}/media`) with camera filter (`cam1..cam4`)
  - “latest by camera” cards for quick operator scanning
  - preview thumbnails + full-resolution open modal
  - capture metadata (timestamp, reason, MIME type, size)
  - copyable asset link (`/api/v1/media/{media_id}/download`) for sharing within the operator perimeter

### Media auth model

Media API endpoints are device-auth scoped. The Device detail page includes a device media token field:

- token is sent as `Authorization: Bearer <token>` for media list/download calls
- token is stored locally per device in browser storage for convenience
- when token is missing/invalid, the UI surfaces error toasts and actionable empty states
