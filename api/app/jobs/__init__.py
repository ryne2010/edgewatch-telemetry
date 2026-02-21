"""One-off job entrypoints.

These modules are designed to run as:

  python -m api.app.jobs.offline_check
  python -m api.app.jobs.analytics_export
  python -m api.app.jobs.simulate_telemetry
  python -m api.app.jobs.retention

In production (GCP), they can be executed via Cloud Run Jobs.
"""
