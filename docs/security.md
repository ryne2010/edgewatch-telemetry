# Security notes (reference)

This repo demonstrates a pragmatic baseline for small fleets.

## Device authentication

- Device sends: `Authorization: Bearer <DEVICE_TOKEN>`
- Server stores:
  - `token_hash` (PBKDF2-HMAC-SHA256)
  - `token_fingerprint` (SHA-256 hex) for efficient lookup

The server never stores the plaintext device token.

Implementation notes:
- We intentionally avoid bcrypt because it truncates inputs at 72 bytes.
- Token hashes are stored as: `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`.

## Admin operations

- Admin endpoints require `X-Admin-Key: <ADMIN_API_KEY>`
- In non-dev environments (`APP_ENV != dev`), the service **fails fast** if `ADMIN_API_KEY` is not set.

In production you would likely:
- replace this with OIDC / IAP / mTLS
- restrict admin endpoints to a private network

## Safer production defaults

- Swagger docs disabled by default (`ENABLE_DOCS` defaults to dev-only)
- CORS allow-origins defaults to **empty** in non-dev
- In-process schedulers disabled by default in non-dev (use Cloud Scheduler/Jobs)

## Recommended hardening (production)

- Mutual TLS for devices (or signed requests)
- Per-device rate limits and ingest quotas
- Device enrollment workflow (rotating tokens, revoke)
- Structured audit logs (who/what/when) + retention controls
- Alert delivery integration (email/SMS/pager)

This repo is intentionally “small but correct.”
