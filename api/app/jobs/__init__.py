"""One-off job entrypoints.

These modules are designed to run as:

  python -m api.app.jobs.offline_check
  python -m api.app.jobs.analytics_export

In production (GCP), they can be executed via Cloud Run Jobs.
"""
