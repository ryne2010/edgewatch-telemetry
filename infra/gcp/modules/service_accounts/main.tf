resource "google_service_account" "runtime" {
  account_id   = var.runtime_account_id
  display_name = var.runtime_display_name
  project      = var.project_id
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset(var.runtime_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_service_account" "ci" {
  count = var.create_ci_account ? 1 : 0

  account_id   = var.ci_account_id
  display_name = var.ci_display_name
  project      = var.project_id
}

resource "google_project_iam_member" "ci_roles" {
  for_each = var.create_ci_account ? toset(var.ci_roles) : []

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ci[0].email}"
}
