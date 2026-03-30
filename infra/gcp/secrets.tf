resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "${var.project_name}-${var.environment}-anthropic-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "anthropic_api_key" {
  secret      = google_secret_manager_secret.anthropic_api_key.id
  secret_data = var.anthropic_api_key
}
