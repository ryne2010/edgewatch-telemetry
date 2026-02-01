/*
  IAM starter pack for a small production-style GCP workspace.

  Design goal:
  - Make it easy to explain in an interview how you model "teams + least privilege".
  - Use Google Groups (Cloud Identity / Workspace) as the principal boundary.
  - Keep application repos focused on *app-scoped* IAM. Project-level IAM is optional and
    should ideally live in the Terraform GCP Platform Baseline repo (repo 3).

  Group naming convention (recommended):
    <prefix>-clients-observers@<domain>
    <prefix>-engineers-min@<domain>
    <prefix>-engineers@<domain>
    <prefix>-auditors@<domain>
    <prefix>-platform-admins@<domain>

  Example for this repo:
    group_prefix = "gkp"
    workspace_domain = "example.com"
    => gkp-engineers@example.com
*/

locals {
  has_workspace = var.workspace_domain != ""

  clients_observers_group = local.has_workspace ? "group:${var.group_prefix}-clients-observers@${var.workspace_domain}" : null
  engineers_min_group     = local.has_workspace ? "group:${var.group_prefix}-engineers-min@${var.workspace_domain}" : null
  engineers_group         = local.has_workspace ? "group:${var.group_prefix}-engineers@${var.workspace_domain}" : null
  auditors_group          = local.has_workspace ? "group:${var.group_prefix}-auditors@${var.workspace_domain}" : null
  platform_admins_group   = local.has_workspace ? "group:${var.group_prefix}-platform-admins@${var.workspace_domain}" : null
}

# --- App-scoped access -------------------------------------------------------
#
# If the service is private (allow_unauthenticated=false), engineers typically need invoker permission.
# In "public demo" mode this is unnecessary.
resource "google_cloud_run_v2_service_iam_member" "engineers_invoker" {
  count = (local.has_workspace && !var.allow_unauthenticated) ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.cloud_run.service_name

  role   = "roles/run.invoker"
  member = local.engineers_group
}

resource "google_cloud_run_v2_service_iam_member" "engineers_min_invoker" {
  count = (local.has_workspace && !var.allow_unauthenticated) ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = module.cloud_run.service_name

  role   = "roles/run.invoker"
  member = local.engineers_min_group
}

# --- Log View access (least-privilege client observability) ------------------
#
# Clients often need access to *just* this service's logs — not the whole project.
# Cloud Logging supports log views + IAM Conditions on roles/logging.viewAccessor.
#
# NOTE: The view is created in log_views.tf and is only present when
# enable_observability && enable_log_views are true.
resource "google_project_iam_member" "clients_log_view_accessor" {
  count = (local.has_workspace && var.enable_observability && var.enable_log_views) ? 1 : 0

  project = var.project_id
  role    = "roles/logging.viewAccessor"
  member  = local.clients_observers_group

  condition {
    title       = "clients-observers-log-view-${var.service_name}"
    description = "Restrict log access to the service-scoped log view only."
    expression  = "resource.name == \"${google_logging_log_view.service_view[0].id}\""
  }
}

# --- Optional project-level IAM ----------------------------------------------
#
# For a "real" team environment, project-level IAM belongs in a centralized "platform baseline"
# repo. We keep it optional here so this repo can be deployed standalone for demos.
#
# Turn on via: enable_project_iam = true
locals {
  project_iam_bindings = (var.enable_project_iam && local.has_workspace) ? [
    # ---- Platform admins: full platform ownership (use carefully) ----
    { role = "roles/resourcemanager.projectIamAdmin", member = local.platform_admins_group },
    { role = "roles/iam.serviceAccountAdmin",        member = local.platform_admins_group },
    { role = "roles/serviceusage.serviceUsageAdmin", member = local.platform_admins_group },
    { role = "roles/run.admin",                      member = local.platform_admins_group },
    { role = "roles/artifactregistry.admin",         member = local.platform_admins_group },
    { role = "roles/secretmanager.admin",            member = local.platform_admins_group },
    { role = "roles/monitoring.admin",               member = local.platform_admins_group },
    { role = "roles/logging.admin",                  member = local.platform_admins_group },

    # ---- Engineers: build + ship + operate ----
    { role = "roles/run.admin",              member = local.engineers_group },
    { role = "roles/artifactregistry.writer", member = local.engineers_group },
    { role = "roles/secretmanager.secretAccessor", member = local.engineers_group },
    { role = "roles/monitoring.viewer",      member = local.engineers_group },
    { role = "roles/logging.viewer",         member = local.engineers_group },

    # ---- Engineers-min: deploy + troubleshoot without full admin ----
    { role = "roles/run.developer",          member = local.engineers_min_group },
    { role = "roles/artifactregistry.reader", member = local.engineers_min_group },
    { role = "roles/monitoring.viewer",      member = local.engineers_min_group },

    # ---- Auditors: read-only visibility ----
    { role = "roles/monitoring.viewer",      member = local.auditors_group },
    { role = "roles/logging.viewer",         member = local.auditors_group },

    # ---- Clients: read-only monitoring + log view (log view handled above) ----
    { role = "roles/monitoring.viewer",      member = local.clients_observers_group },
  ] : []
}

resource "google_project_iam_member" "project_iam" {
  for_each = {
    for b in local.project_iam_bindings : "${b.role}|${b.member}" => b
  }

  project = var.project_id
  role    = each.value.role
  member  = each.value.member
}
