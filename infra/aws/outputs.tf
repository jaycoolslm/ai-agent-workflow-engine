output "bucket_name" {
  description = "S3 bucket for workflow manifests and data"
  value       = aws_s3_bucket.workflows.id
}

output "ecr_repository_url" {
  description = "ECR repository URL for the agent image"
  value       = aws_ecr_repository.agent.repository_url
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.main.arn
}

output "lambda_function_name" {
  description = "Lambda router function name (for viewing logs)"
  value       = aws_lambda_function.router.function_name
}

output "ecr_push_commands" {
  description = "Commands to build and push the agent image"
  value       = <<-EOT
    # Login to ECR
    aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${aws_ecr_repository.agent.repository_url}

    # Build and push (run from repo root)
    docker build -f Dockerfile.agent -t ${aws_ecr_repository.agent.repository_url}:${var.agent_image_tag} .
    docker push ${aws_ecr_repository.agent.repository_url}:${var.agent_image_tag}
  EOT
}

output "trigger_workflow_command" {
  description = "Command to trigger a sample workflow"
  value       = "aws s3 cp sample-manifest.json s3://${aws_s3_bucket.workflows.id}/runs/run_001/manifest.json"
}
