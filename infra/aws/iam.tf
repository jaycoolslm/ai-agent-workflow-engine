# =============================================================================
# PHASE 1: Loose permissions to validate e2e pipeline.
# Every broad policy is marked with "PHASE 2: tighten" for scoping down later.
# =============================================================================

# -----------------------------------------------------------------------------
# Role 1: Lambda Execution Role
# -----------------------------------------------------------------------------
resource "aws_iam_role" "lambda_execution" {
  name = "${var.project_name}-lambda-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# CloudWatch Logs for Lambda
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda needs: S3 read/write, ECS RunTask, IAM PassRole
resource "aws_iam_policy" "lambda_custom" {
  name        = "${var.project_name}-lambda-custom"
  description = "Lambda router: S3 access, ECS RunTask, PassRole"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        # PHASE 2: tighten to ["s3:GetObject", "s3:PutObject"]
        Action   = "s3:*"
        Resource = [
          aws_s3_bucket.workflows.arn,
          "${aws_s3_bucket.workflows.arn}/*",
        ]
      },
      {
        Sid    = "ECSRunTask"
        Effect = "Allow"
        Action = "ecs:RunTask"
        # PHASE 2: tighten to aws_ecs_task_definition.agent.arn (without revision)
        Resource = "*"
      },
      {
        Sid    = "PassRole"
        Effect = "Allow"
        Action = "iam:PassRole"
        # PHASE 2: tighten to [aws_iam_role.ecs_execution.arn, aws_iam_role.ecs_task.arn]
        Resource = "*"
        Condition = {
          StringLike = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_custom" {
  role       = aws_iam_role.lambda_execution.name
  policy_arn = aws_iam_policy.lambda_custom.arn
}

# -----------------------------------------------------------------------------
# Role 2: ECS Task Execution Role (pulls images, writes logs, fetches secrets)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "ecs_execution" {
  name = "${var.project_name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# ECR pull + CloudWatch Logs
resource "aws_iam_role_policy_attachment" "ecs_execution_base" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Secrets Manager access for ANTHROPIC_API_KEY
resource "aws_iam_policy" "ecs_execution_secrets" {
  name        = "${var.project_name}-ecs-execution-secrets"
  description = "ECS execution role: Secrets Manager access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SecretsAccess"
      Effect = "Allow"
      Action = "secretsmanager:GetSecretValue"
      # PHASE 2: tighten to [aws_secretsmanager_secret.anthropic_api_key.arn]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = aws_iam_policy.ecs_execution_secrets.arn
}

# -----------------------------------------------------------------------------
# Role 3: ECS Task Role (what the container itself can do at runtime)
# -----------------------------------------------------------------------------
resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# PHASE 2: replace with custom policy scoped to workflow bucket only:
# Actions: s3:GetObject, s3:PutObject, s3:ListBucket, s3:CopyObject, s3:HeadObject
# Resource: [aws_s3_bucket.workflows.arn, "${aws_s3_bucket.workflows.arn}/*"]
resource "aws_iam_role_policy_attachment" "ecs_task_s3" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}
