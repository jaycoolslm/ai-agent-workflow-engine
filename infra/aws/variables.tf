variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
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
  description = "Docker image tag for the agent container in ECR"
  type        = string
  default     = "latest"
}

variable "container_cpu" {
  description = "Fargate task CPU units (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "container_memory" {
  description = "Fargate task memory in MB"
  type        = number
  default     = 4096
}

variable "bucket_name" {
  description = "S3 bucket name. Leave empty to auto-generate from project name."
  type        = string
  default     = ""
}

locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "${var.project_name}-${var.environment}-workflows"
}
