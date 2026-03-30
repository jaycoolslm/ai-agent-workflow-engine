# Enable required GCP APIs. These are project-level and must be active
# before any resources that depend on them can be created.

resource "google_project_service" "required" {
  for_each = toset([
    "storage.googleapis.com",
    "cloudfunctions.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "eventarc.googleapis.com",
    "pubsub.googleapis.com",
  ])

  project = var.gcp_project
  service = each.value

  disable_on_destroy = false
}
