resource "google_storage_bucket" "workflows" {
  name     = local.bucket_name
  location = var.gcp_region

  force_destroy               = true # MVP: allows terraform destroy without manual object cleanup
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "AbortIncompleteMultipartUpload"
    }
  }
}
