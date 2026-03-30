data "archive_file" "router" {
  type        = "zip"
  source_dir  = "${path.module}/function"
  output_path = "${path.module}/.build/router.zip"
}

resource "google_storage_bucket" "function_source" {
  name     = "${var.project_name}-${var.environment}-function-source"
  location = var.gcp_region

  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "router_source" {
  name   = "router-${data.archive_file.router.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.router.output_path
}

resource "google_cloudfunctions2_function" "router" {
  name     = "${var.project_name}-router"
  location = var.gcp_region

  build_config {
    runtime     = "python312"
    entry_point = "handler"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.router_source.name
      }
    }
  }

  service_config {
    max_instance_count    = 10
    available_memory      = "256M"
    timeout_seconds       = 60
    service_account_email = google_service_account.router.email

    environment_variables = {
      GCP_PROJECT        = var.gcp_project
      GCP_REGION         = var.gcp_region
      CLOUD_RUN_JOB_NAME = google_cloud_run_v2_job.agent.name
      BUCKET_NAME        = google_storage_bucket.workflows.name
      AGENT_RUNTIME      = var.agent_runtime
      LLM_MODEL          = var.llm_model
    }
  }

  event_trigger {
    event_type   = "google.cloud.storage.object.v1.finalized"
    retry_policy = "DO_NOT_RETRY"

    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.workflows.name
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.router_eventarc,
  ]
}
