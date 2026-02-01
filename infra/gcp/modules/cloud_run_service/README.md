# module: cloud_run_service

Deploys a **Cloud Run (v2) service** with optional:
- unauthenticated access (public)
- Secret Manager env vars (latest version)
- Serverless VPC Access connector

Defaults are chosen for low-cost demos:
- `min_instances = 0` (scale to zero)
- modest `max_instances`
