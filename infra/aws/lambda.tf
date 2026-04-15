data "archive_file" "router" {
  type        = "zip"
  source_file = "${path.module}/lambda/router.py"
  output_path = "${path.module}/.build/router.zip"
}

resource "aws_lambda_function" "router" {
  function_name    = "${var.project_name}-router"
  role             = aws_iam_role.lambda_execution.arn
  handler          = "router.handler"
  runtime          = "python3.12"
  filename         = data.archive_file.router.output_path
  source_code_hash = data.archive_file.router.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      ECS_CLUSTER_ARN    = aws_ecs_cluster.main.arn
      TASK_DEFINITION_ARN = aws_ecs_task_definition.agent.arn
      SUBNET_IDS         = jsonencode(data.aws_subnets.default.ids)
      SECURITY_GROUP_IDS = jsonencode([aws_security_group.agent_tasks.id])
      BUCKET_NAME        = aws_s3_bucket.workflows.id
      CONTAINER_NAME     = "agent"
      AGENT_RUNTIME      = var.agent_runtime
      LLM_MODEL          = var.llm_model
    }
  }
}

# Allow S3 to invoke the Lambda.
resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.workflows.arn
}
