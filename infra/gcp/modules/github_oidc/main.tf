locals {
  branch_conditions = length(var.allowed_branches) > 0 ? [
    for b in var.allowed_branches : "assertion.ref == 'refs/heads/${b}'"
  ] : []
  attribute_condition = length(local.branch_conditions) > 0
    ? "assertion.repository == '${var.github_repository}' && (${join(" || ", local.branch_conditions)})"
    : "assertion.repository == '${var.github_repository}'"
}

resource "google_iam_workload_identity_pool" "pool" {
  provider                    = google-beta
  project                     = var.project_id
  workload_identity_pool_id   = var.pool_id
  display_name                = var.pool_display_name
  description                 = var.pool_description
  disabled                    = false
}

resource "google_iam_workload_identity_pool_provider" "provider" {
  provider                           = google-beta
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.pool.workload_identity_pool_id
  workload_identity_pool_provider_id = var.provider_id
  display_name                       = var.provider_display_name
  description                        = var.provider_description
  disabled                           = false

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  attribute_condition = local.attribute_condition

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "wif_user" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.service_account_email}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "token_creator" {
  count = var.grant_token_creator ? 1 : 0

  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.pool.name}/attribute.repository/${var.github_repository}"
}
