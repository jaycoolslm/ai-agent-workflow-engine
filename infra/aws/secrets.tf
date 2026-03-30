resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${var.project_name}/${var.environment}/anthropic-api-key"
  description             = "Anthropic API key for Claude Agent SDK"
  recovery_window_in_days = 0 # MVP: allow immediate deletion on terraform destroy
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = var.anthropic_api_key
}
