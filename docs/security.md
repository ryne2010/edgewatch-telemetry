# Security notes (reference)

This repo demonstrates a pragmatic baseline for small fleets.

## Device authentication

- Device sends: `Authorization: Bearer <DEVICE_TOKEN>`
- Server stores:
  - `token_hash` (bcrypt)
  - `token_fingerprint` (SHA-256 hex) for efficient lookup

The server never stores the plaintext device token.

## Admin operations

- Admin endpoints require `X-Admin-Key: <ADMIN_API_KEY>`
- In production you would:
  - replace this with OIDC / IAP / mTLS
  - restrict admin endpoints to a private network

## Recommended hardening (production)

- Mutual TLS for devices (or signed requests)
- Per-device rate limits and ingest quotas
- Device enrollment workflow (rotating tokens, revoke)
- Restrict CORS and disable Swagger in production
- Structured audit logs (who/what/when) + retention controls
- Alert delivery integration (email/SMS/pager)

This repo is intentionally “small but correct.”
