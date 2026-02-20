# Security notes

See `docs/security.md` for the detailed threat model.

Highlights:
- Device auth uses opaque tokens; server stores only PBKDF2-HMAC-SHA256 hashes.
- Admin endpoints require `ADMIN_API_KEY`.
- In cloud deployments, store secrets in Secret Manager and restrict who can access them.

For demo purposes, the default local stack uses dev credentials in `.env.example`.
Do not expose the local deployment to the internet without hardening.
