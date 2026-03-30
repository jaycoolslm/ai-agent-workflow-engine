resource "google_artifact_registry_repository" "agent" {
  location      = var.gcp_region
  repository_id = "${var.project_name}-agent"
  format        = "DOCKER"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-last-5-untagged"
    action = "KEEP"

    most_recent_versions {
      keep_count = 5
    }

    condition {
      tag_state = "UNTAGGED"
    }
  }

  depends_on = [google_project_service.required]
}
