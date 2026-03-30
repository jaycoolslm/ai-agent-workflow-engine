# Default VPC — all accounts have one unless manually deleted.
data "aws_vpc" "default" {
  default = true
}

# Public subnets in the default VPC (Fargate tasks need outbound internet).
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

# Security group for Fargate tasks: egress-only (no inbound traffic).
resource "aws_security_group" "agent_tasks" {
  name        = "${var.project_name}-agent-tasks"
  description = "Egress-only SG for agent Fargate tasks"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "agent_all_outbound" {
  security_group_id = aws_security_group.agent_tasks.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Allow all outbound (Anthropic API, ECR, S3, CloudWatch)"
}
