terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # MVP: local state. Add GCS backend when you have a second developer:
  # backend "gcs" {
  #   bucket = "your-terraform-state-bucket"
  #   prefix = "agent-workflow-engine/terraform.tfstate"
  # }
}

provider "google" {
  project = var.gcp_project
  region  = var.gcp_region

  default_labels = {
    project     = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  }
}
