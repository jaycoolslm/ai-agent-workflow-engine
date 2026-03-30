# GCP Deployment

Deploy the workflow engine to GCP using Terraform (GCS + Cloud Functions + Cloud Run Jobs).

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.5
- [gcloud CLI](https://cloud.google.com/sdk/docs/install) configured (`gcloud auth login`)
- Docker Desktop running
- A GCP project with billing enabled
- An Anthropic API key

## Deploy

```bash
cd infra/gcp
terraform init
terraform apply -var="gcp_project=my-project-id" -var="anthropic_api_key=sk-ant-..."
```

To avoid entering variables each time, create `infra/gcp/terraform.tfvars`:

```hcl
gcp_project       = "my-project-id"
anthropic_api_key = "sk-ant-..."
```

This file is gitignored.

## Build and Push the Agent Image

**Important:** If you're on Apple Silicon (M1/M2/M3), you must build for `linux/amd64` since Cloud Run runs x86_64:

```bash
# Configure Docker for Artifact Registry (use the region from terraform output)
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build for the correct platform and push
docker build --platform linux/amd64 -f Dockerfile.agent -t <artifact_registry_url>/agent:latest .
docker push <artifact_registry_url>/agent:latest
```

Run `terraform output` to get the exact Artifact Registry URL and commands.

## Trigger a Workflow

```bash
gsutil cp sample-manifest.json gs://<bucket_name>/runs/run_001/manifest.json
```

This triggers: GCS event -> Cloud Function router -> Cloud Run Job -> agent runs -> writes manifest -> Cloud Function re-triggers for next step.

## Watch Logs

```bash
# Cloud Function router logs
gcloud functions logs read agent-workflow-engine-router --region us-central1 --gen2

# Cloud Run Job execution logs
gcloud run jobs executions list --job agent-workflow-engine-agent --region us-central1
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=agent-workflow-engine-agent" --limit 50
```

## Check Workflow Status

```bash
gsutil cat gs://<bucket_name>/runs/run_001/manifest.json
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `gcp_project` | -- | GCP project ID (required) |
| `gcp_region` | `us-central1` | GCP region |
| `environment` | `dev` | Environment name |
| `anthropic_api_key` | -- | Anthropic API key (sensitive) |
| `agent_image_tag` | `latest` | Artifact Registry image tag |
| `container_cpu` | `1` | Cloud Run Job CPU limit |
| `container_memory` | `4Gi` | Cloud Run Job memory limit |
| `agent_runtime` | `claude` | Agent runtime |
| `llm_model` | `""` | LLM model override |

## Teardown

```bash
terraform destroy
```

Enter any value for `anthropic_api_key` when prompted (it's not used during destroy).
