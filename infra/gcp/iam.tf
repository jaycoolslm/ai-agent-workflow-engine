# =============================================================================
# PHASE 1: Loose permissions to validate e2e pipeline.
# Every broad grant is marked with "PHASE 2: tighten" for scoping down later.
# =============================================================================

# -----------------------------------------------------------------------------
# Service Account 1: Cloud Function (router)
# -----------------------------------------------------------------------------
resource "google_service_account" "router" {
  account_id   = "${var.project_name}-router"
  display_name = "Cloud Function router for ${var.project_name}"
}

# PHASE 2: tighten to roles/storage.objectViewer + roles/storage.objectCreator
resource "google_storage_bucket_iam_member" "router_storage" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.router.email}"
}

# Execute Cloud Run Jobs
resource "google_project_iam_member" "router_run_invoker" {
  project = var.gcp_project
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# Create job executions with overrides
resource "google_project_iam_member" "router_run_developer" {
  project = var.gcp_project
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# Receive Eventarc events
resource "google_project_iam_member" "router_eventarc" {
  project = var.gcp_project
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# Pull images from Artifact Registry
resource "google_project_iam_member" "router_ar_reader" {
  project = var.gcp_project
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.router.email}"
}

# -----------------------------------------------------------------------------
# Service Account 2: Cloud Run Job (agent container)
# -----------------------------------------------------------------------------
resource "google_service_account" "agent" {
  account_id   = "${var.project_name}-agent"
  display_name = "Cloud Run Job agent for ${var.project_name}"
}

# PHASE 2: tighten to roles/storage.objectViewer + roles/storage.objectCreator
resource "google_storage_bucket_iam_member" "agent_storage" {
  bucket = google_storage_bucket.workflows.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.agent.email}"
}

# Access secrets from Secret Manager
resource "google_project_iam_member" "agent_secrets" {
  project = var.gcp_project
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

# Pull images from Artifact Registry
resource "google_artifact_registry_repository_iam_member" "agent_ar_reader" {
  project    = var.gcp_project
  location   = var.gcp_region
  repository = google_artifact_registry_repository.agent.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.agent.email}"
}
