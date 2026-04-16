variable "gcp_project" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name, used as prefix for all resources"
  type        = string
  default     = "agent-workflow-engine"
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude Agent SDK"
  type        = string
  sensitive   = true
  default     = ""
}

variable "openai_api_key" {
  description = "OpenAI API key for Codex runtime"
  type        = string
  sensitive   = true
  default     = ""
}

variable "agent_image_tag" {
  description = "Docker image tag for the agent container in Artifact Registry"
  type        = string
  default     = "latest"
}

variable "container_cpu" {
  description = "Cloud Run Job CPU limit (e.g. \"1\", \"2\")"
  type        = string
  default     = "1"
}

variable "container_memory" {
  description = "Cloud Run Job memory limit (e.g. \"4Gi\")"
  type        = string
  default     = "4Gi"
}

variable "bucket_name" {
  description = "GCS bucket name. Leave empty to auto-generate from project name."
  type        = string
  default     = ""
}

variable "agent_runtime" {
  description = "Agent runtime to use (e.g. claude)"
  type        = string
  default     = "claude"
}

variable "llm_model" {
  description = "LLM model override (leave empty for default)"
  type        = string
  default     = ""
}

locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project_name}-${var.environment}-workflows"
}
