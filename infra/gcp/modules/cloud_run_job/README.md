# Module: cloud_run_job

Creates a **Cloud Run v2 Job** with optional Secret Manager env vars and optional Serverless VPC Access.

Use cases:
- one-off DB migrations
- scheduled maintenance jobs (triggered by Cloud Scheduler)
- batch processing

This module mirrors the shape of `modules/cloud_run_service` to keep the repo consistent.
