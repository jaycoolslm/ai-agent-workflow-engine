variable "azure_region" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
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
}

variable "agent_image_tag" {
  description = "Docker image tag for the agent container in ACR"
  type        = string
  default     = "latest"
}

variable "container_cpu" {
  description = "ACI container CPU cores"
  type        = number
  default     = 1.0
}

variable "container_memory_gb" {
  description = "ACI container memory in GB"
  type        = number
  default     = 4.0
}

variable "storage_account_name" {
  description = "Storage account name. Leave empty to auto-generate."
  type        = string
  default     = ""
}

locals {
  # Azure storage account names: 3-24 chars, lowercase alphanumeric only
  storage_account_name = var.storage_account_name != "" ? var.storage_account_name : replace(
    "${substr(var.project_name, 0, 14)}${var.environment}", "-", ""
  )
  container_name = "workflows"
}
