output "bucket_name" {
  description = "GCS bucket for workflow manifests and data"
  value       = google_storage_bucket.workflows.name
}

output "artifact_registry_url" {
  description = "Artifact Registry Docker image path prefix"
  value       = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.agent.repository_id}"
}

output "cloud_run_job_name" {
  description = "Cloud Run Job name"
  value       = google_cloud_run_v2_job.agent.name
}

output "cloud_function_name" {
  description = "Cloud Function router name (for viewing logs)"
  value       = google_cloudfunctions2_function.router.name
}

output "docker_push_commands" {
  description = "Commands to build and push the agent image"
  value       = <<-EOT
    # Configure Docker for Artifact Registry
    gcloud auth configure-docker ${var.gcp_region}-docker.pkg.dev

    # Build and push (run from repo root)
    docker build -f Dockerfile.agent -t ${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.agent.repository_id}/agent:${var.agent_image_tag} .
    docker push ${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.agent.repository_id}/agent:${var.agent_image_tag}
  EOT
}

output "trigger_workflow_command" {
  description = "Command to trigger a sample workflow"
  value       = "gsutil cp sample-manifest.json gs://${google_storage_bucket.workflows.name}/runs/run_001/manifest.json"
}
