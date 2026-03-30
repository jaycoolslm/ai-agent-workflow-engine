# AWS Deployment

Deploy the workflow engine to AWS using Terraform (S3 + Lambda + ECS Fargate).

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- AWS CLI configured (`aws configure`)
- Docker Desktop running
- An Anthropic API key

## Deploy

```bash
cd infra/aws
terraform init
terraform apply -var="anthropic_api_key=sk-ant-..."
```

To avoid entering the key each time, create `infra/aws/terraform.tfvars`:

```hcl
anthropic_api_key = "sk-ant-..."
```

This file is gitignored.

## Build and Push the Agent Image

**Important:** If you're on Apple Silicon (M1/M2/M3), you must build for `linux/amd64` since Fargate runs x86_64:

```bash
# Login to ECR (use the URL from terraform output)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ecr_repository_url>

# Build for the correct platform and push
docker build --platform linux/amd64 -f Dockerfile.agent -t <ecr_repository_url>:latest .
docker push <ecr_repository_url>:latest
```

Run `terraform output` to get the exact ECR URL and commands.

## Trigger a Workflow

```bash
aws s3 cp sample-manifest.json s3://<bucket_name>/runs/run_001/manifest.json
```

This triggers: S3 event → Lambda router → ECS Fargate task → agent runs → writes manifest → Lambda re-triggers for next step.

## Watch Logs

```bash
# Lambda router logs
aws logs tail /aws/lambda/agent-workflow-engine-router --follow

# Agent container logs (appears after ~60-90s cold start)
aws logs tail /ecs/agent-workflow-engine-agent --follow
```

## Check Workflow Status

```bash
aws s3 cp s3://<bucket_name>/runs/run_001/manifest.json -
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `aws_region` | `us-east-1` | AWS region |
| `environment` | `dev` | Environment name |
| `anthropic_api_key` | — | Anthropic API key (sensitive) |
| `agent_image_tag` | `latest` | ECR image tag |
| `container_cpu` | `1024` | Fargate CPU units (1024 = 1 vCPU) |
| `container_memory` | `4096` | Fargate memory in MB |

## Teardown

```bash
terraform destroy
```

Enter any value for `anthropic_api_key` when prompted (it's not used during destroy).
