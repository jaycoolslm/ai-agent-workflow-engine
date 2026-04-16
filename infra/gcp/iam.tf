# =============================================================================
# PHASE 2: Least-privilege IAM — every grant scoped to specific resources.
# =============================================================================

# -----------------------------------------------------------------------------
# Service Account 1: Cloud Function (router)
# -----------------------------------------------------------------------------
resource "google_service_account" "router" {
  account_id   = "${var.project_name}-router"
  display_name = "Cloud Function router for ${var.project_name}"
}

# Storage: read objects + create new objects (no delete/overwrite admin)
resource "google_storage_bucket_iam_member" "router_storage_viewer" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.router.email}"
}

resource "google_storage_bucket_iam_member" "router_storage_creator" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.router.email}"
}

# Execute Cloud Run Jobs
resource "google_project_iam_member" "router_run_invoker" {
  project = var.gcp_project
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# Create job executions with overrides — scoped to the agent job
resource "google_cloud_run_v2_job_iam_member" "router_run_developer" {
  project  = var.gcp_project
  location = var.gcp_region
  name     = google_cloud_run_v2_job.agent.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.router.email}"
}

# Receive Eventarc events
resource "google_project_iam_member" "router_eventarc" {
  project = var.gcp_project
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# Pull images from Artifact Registry — scoped to the repository
resource "google_artifact_registry_repository_iam_member" "router_ar_reader" {
  project    = var.gcp_project
  location   = var.gcp_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.router.email}"
}

# -----------------------------------------------------------------------------
# Service Account 2: Cloud Run Job (agent container)
# -----------------------------------------------------------------------------
resource "google_service_account" "agent" {
  account_id   = "${var.project_name}-agent"
  display_name = "Cloud Run Job agent for ${var.project_name}"
}

# Storage: read objects + create new objects (no delete/overwrite admin)
resource "google_storage_bucket_iam_member" "agent_storage_viewer" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_storage_bucket_iam_member" "agent_storage_creator" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.agent.email}"
}

# Secret Manager: scoped to specific secrets only
resource "google_secret_manager_secret_iam_member" "agent_secret_anthropic" {
  project   = var.gcp_project
  secret_id = google_secret_manager_secret.anthropic_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_secret_manager_secret_iam_member" "agent_secret_openai" {
  project   = var.gcp_project
  secret_id = google_secret_manager_secret.openai_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

# Pull images from Artifact Registry — scoped to the repository
resource "google_artifact_registry_repository_iam_member" "agent_ar_reader" {
  project    = var.gcp_project
  location   = var.gcp_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.agent.email}"
}
