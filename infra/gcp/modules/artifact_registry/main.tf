resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.location
  repository_id = var.repository_id
  format        = var.format
  description   = var.description
  labels        = var.labels

  # Hygiene: cleanup policies are OFF by default unless you provide cleanup_policies.
  # We keep dry-run ON by default to prevent surprise deletions.
  cleanup_policy_dry_run = var.cleanup_policy_dry_run

  dynamic "cleanup_policies" {
    for_each = var.cleanup_policies
    content {
      id     = cleanup_policies.value.id
      action = cleanup_policies.value.action

      dynamic "condition" {
        for_each = cleanup_policies.value.condition == null ? [] : [cleanup_policies.value.condition]
        content {
          tag_state             = try(condition.value.tag_state, null)
          tag_prefixes          = try(condition.value.tag_prefixes, null)
          package_name_prefixes = try(condition.value.package_name_prefixes, null)
          version_name_prefixes = try(condition.value.version_name_prefixes, null)
          older_than            = try(condition.value.older_than, null)
          newer_than            = try(condition.value.newer_than, null)
        }
      }

      dynamic "most_recent_versions" {
        for_each = cleanup_policies.value.most_recent_versions == null ? [] : [cleanup_policies.value.most_recent_versions]
        content {
          package_name_prefixes = try(most_recent_versions.value.package_name_prefixes, null)
          keep_count            = most_recent_versions.value.keep_count
        }
      }
    }
  }
}
