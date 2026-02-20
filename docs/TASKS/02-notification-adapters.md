# Task: Notification delivery adapters (Slack/email/webhook)

## Intent

Add pluggable notification adapters so routed alerts can reach real operators.

## Acceptance criteria

- Notifications are delivered through at least one adapter:
  - Slack webhook OR email (SMTP) OR generic webhook.
- Delivery failures are captured and do not crash the API.
- Secrets are stored and handled safely (no secret logging).

## Design notes

- Keep adapters behind an interface so the core alert logic stays testable.
- For the Cloud Run demo posture, prefer:
  - Secret Manager for adapter credentials
  - structured logs for delivery attempts

## Validation

```bash
make lint
make typecheck
make test
```
