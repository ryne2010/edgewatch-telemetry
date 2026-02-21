# Security notes

See `docs/security.md` for the detailed threat model and hardening guidance.

Highlights:

- Device auth uses opaque tokens; the server stores only PBKDF2-HMAC-SHA256 hashes.
- Admin endpoints are optional:
  - `ENABLE_ADMIN_ROUTES=0` removes `/api/v1/admin/*` entirely.
  - `ADMIN_AUTH_MODE=key|none` controls whether admin routes require `X-Admin-Key` or trust an infrastructure perimeter.
- In cloud deployments, store secrets in Secret Manager and restrict who can access them.
- If the service is public, add a perimeter rate limiter/WAF (Cloud Armor/API Gateway/etc) to control cost and abuse.

For demo purposes, the default local stack uses dev credentials in `.env.example`.
Do not expose a demo deployment to the internet without additional hardening.
