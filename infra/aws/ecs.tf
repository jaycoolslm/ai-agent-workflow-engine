resource "aws_cloudwatch_log_group" "agent" {
  name              = "/ecs/${var.project_name}-agent"
  retention_in_days = 14
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "disabled" # MVP: enable later if needed
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 1
    weight            = 1
  }
}

resource "aws_ecs_task_definition" "agent" {
  family                   = "${var.project_name}-agent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.container_cpu
  memory                   = var.container_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = "agent"
      image     = "${aws_ecr_repository.agent.repository_url}:${var.agent_image_tag}"
      essential = true

      # Fixed env vars (same for every task invocation)
      environment = [
        { name = "STORAGE_BACKEND", value = "s3" },
        { name = "S3_ENDPOINT", value = "" },
        { name = "BUCKET", value = local.bucket_name },
      ]

      # PLUGIN_NAME and RUN_PREFIX are passed as overrides in run_task()
      # so we don't need a new task definition revision per workflow step.

      # Secrets injected from Secrets Manager at container start
      secrets = [
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.agent.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "agent"
        }
      }
    }
  ])
}
