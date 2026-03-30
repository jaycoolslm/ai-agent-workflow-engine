resource "aws_ecr_repository" "agent" {
  name                 = "${var.project_name}/agent"
  image_tag_mutability = "MUTABLE" # allows reusing "latest" tag during dev
  force_delete         = true      # MVP: allows terraform destroy without manual image cleanup

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "agent" {
  repository = aws_ecr_repository.agent.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 untagged images"
        selection = {
          tagStatus   = "untagged"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
