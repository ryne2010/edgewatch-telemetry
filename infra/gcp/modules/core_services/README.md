# module: core_services

Enables a standard set of Google APIs used by the baseline (Cloud Run, Artifact Registry, Logging/Monitoring, Pub/Sub, etc.).

## Notes
- Enabling APIs is often a prerequisite for other resources.
- Disabling APIs on destroy is off by default to avoid surprising side effects.
