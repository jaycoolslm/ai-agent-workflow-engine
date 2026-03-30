resource "google_cloud_run_v2_job" "agent" {
  name                = "${var.project_name}-agent"
  location            = var.gcp_region
  deletion_protection = false # MVP: allows terraform destroy without manual cleanup

  template {
    template {
      service_account = google_service_account.agent.email

      containers {
        image = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project}/${google_artifact_registry_repository.agent.repository_id}/agent:${var.agent_image_tag}"

        # Fixed env vars (same for every job execution)
        env {
          name  = "STORAGE_BACKEND"
          value = "gcs"
        }
        env {
          name  = "BUCKET"
          value = google_storage_bucket.workflows.name
        }
        env {
          name  = "GCP_PROJECT"
          value = var.gcp_project
        }
        env {
          name  = "AGENT_RUNTIME"
          value = var.agent_runtime
        }
        env {
          name  = "LLM_MODEL"
          value = var.llm_model
        }

        # PLUGIN_NAME and RUN_PREFIX are passed as overrides in job execution
        # so we don't need a new job revision per workflow step.

        # Secrets injected from Secret Manager at container start
        env {
          name = "ANTHROPIC_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.anthropic_api_key.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = var.container_cpu
            memory = var.container_memory
          }
        }
      }

      timeout     = "3600s"
      max_retries = 0
    }
  }

  depends_on = [google_project_service.required]
}
