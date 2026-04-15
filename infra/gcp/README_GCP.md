# GCP Infrastructure — AI Agent Workflow Engine

> **Terraform-managed** infrastructure for running the AI Agent Workflow Engine
> on Google Cloud Platform using **GCS**, **Cloud Functions**, **Cloud Run Jobs**,
> **Artifact Registry**, and **Secret Manager**.

---

## Architecture Overview

```
┌──────────────┐     GCS finalize      ┌────────────────────┐     Cloud Run     ┌──────────────────┐
│  gsutil cp   │ ──────────────────────→│  Cloud Function    │ ──────────────→   │  Cloud Run Job   │
│  manifest    │                        │  (Router)          │   Job execution   │  (Agent Container)│
│  → GCS       │                        │  main.py           │                   │  entrypoint.py   │
└──────────────┘                        └────────┬───────────┘                   └────────┬─────────┘
                                                 │                                        │
                                                 │ reads manifest                         │ reads manifest
                                                 │ from GCS                               │ runs AI runtime
                                                 │                                        │ writes outputs
                                                 ↓                                        │ advances step
                                        ┌────────────────┐                               │
                                        │  GCS Bucket    │ ←─────────────────────────────┘
                                        │  (workflows)   │   writes updated manifest
                                        └────────────────┘   → triggers next Cloud Function
```

### Event-Driven Execution Loop

1. Upload `manifest.json` to GCS (via `gsutil`, SDK, or prior step).
2. **GCS finalize event** triggers the Cloud Function (router).
3. Cloud Function reads the manifest, finds the next `pending` step,
   marks it `running`, and launches a **Cloud Run Job** with `PLUGIN_NAME`
   and `RUN_PREFIX` overrides.
4. Cloud Run Job container (`entrypoint.py`) reads the manifest, downloads
   input files, runs the AI runtime, uploads outputs, advances `current_step`,
   and writes the updated manifest back to GCS.
5. Manifest write triggers step 2 again — loop continues until workflow is
   `complete` or `failed`.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Terraform** | ≥ 1.5 | `terraform -version` |
| **gcloud CLI** | latest | `gcloud version` — [install guide](https://cloud.google.com/sdk/docs/install) |
| **Docker Desktop** | latest | Required for building the agent image |
| **GCP Project** | — | With billing enabled |
| **Anthropic API key** | — | For Claude runtime (`sk-ant-...`) |
| **OpenAI API key** | — | For Codex runtime (optional) |

### GCP IAM Permissions Required

The user or service account running `terraform apply` needs:

- `roles/editor` (broad) **or** more granular:
  - `roles/storage.admin`
  - `roles/cloudfunctions.developer`
  - `roles/run.admin`
  - `roles/artifactregistry.admin`
  - `roles/secretmanager.admin`
  - `roles/iam.serviceAccountAdmin`
  - `roles/serviceusage.serviceUsageAdmin`

---

## Quick Start

```bash
# 1. Authenticate
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID

# 2. Navigate to the GCP infra directory
cd infra/gcp

# 3. Create a terraform.tfvars file (git-ignored)
cat > terraform.tfvars <<EOF
gcp_project       = "your-gcp-project-id"
gcp_region        = "us-central1"
environment       = "dev"
anthropic_api_key = "sk-ant-your-key-here"
openai_api_key    = "sk-your-openai-key"      # optional
agent_runtime     = "claude"                   # or: echo, codex, deepagent
EOF

# 4. Initialize Terraform
terraform init

# 5. Preview changes
terraform plan

# 6. Apply infrastructure
terraform apply
```

---

## Step-by-Step Deployment Guide

### Step 1: Terraform Init

```bash
cd infra/gcp
terraform init
```

This downloads the required providers:
- `hashicorp/google ~> 6.0` — GCP resource management
- `hashicorp/archive ~> 2.0` — Zip the Cloud Function source

### Step 2: Configure Variables

Create `terraform.tfvars` in `infra/gcp/` (this file is `.gitignore`d):

```hcl
gcp_project       = "plazatech-workflow-dev"
gcp_region        = "us-central1"
environment       = "dev"
anthropic_api_key = "sk-ant-..."
openai_api_key    = ""
agent_runtime     = "claude"
llm_model         = ""                  # Leave empty for default
container_cpu     = "1"
container_memory  = "4Gi"
agent_image_tag   = "latest"
```

### Step 3: Validate Configuration

```bash
terraform validate
# Expected: "Success! The configuration is valid."

terraform fmt -check -recursive
# Expected: no output (all files properly formatted)
```

### Step 4: Plan & Apply

```bash
# Preview what will be created
terraform plan -out=tfplan

# Apply (creates ~15 resources)
terraform apply tfplan
```

**Resources provisioned:**

| Resource | Type | Purpose |
|----------|------|---------|
| GCS Bucket (workflows) | `google_storage_bucket` | Manifest + file storage |
| GCS Bucket (function source) | `google_storage_bucket` | Cloud Function deployment artifact |
| Artifact Registry | `google_artifact_registry_repository` | Docker image registry |
| Cloud Run Job | `google_cloud_run_v2_job` | Agent container execution |
| Cloud Function | `google_cloudfunctions2_function` | Event-driven router |
| Secret Manager (×2) | `google_secret_manager_secret` | API keys (Anthropic, OpenAI) |
| Service Account (router) | `google_service_account` | Cloud Function identity |
| Service Account (agent) | `google_service_account` | Cloud Run Job identity |
| IAM Bindings (×7) | Various | Permissions for service accounts |
| GCP API Enablements (×8) | `google_project_service` | Required API activation |

### Step 5: Build & Push the Agent Image

```bash
# Get Artifact Registry URL from Terraform output
AR_URL=$(terraform output -raw artifact_registry_url)

# Configure Docker for Artifact Registry
gcloud auth configure-docker $(terraform output -raw artifact_registry_url | cut -d/ -f1)

# Build for linux/amd64 (required for Cloud Run)
docker build --platform linux/amd64 \
  -f ../../Dockerfile.agent \
  -t ${AR_URL}/agent:latest \
  ../..

# Push
docker push ${AR_URL}/agent:latest
```

> **Apple Silicon (M1/M2/M3) users:** The `--platform linux/amd64` flag is
> essential. Cloud Run only supports x86_64.

### Step 6: Trigger a Workflow

```bash
BUCKET=$(terraform output -raw bucket_name)

# Upload sample manifest
gsutil cp ../../sample-manifest.json gs://${BUCKET}/runs/run_001/manifest.json
```

This triggers the event loop:
1. GCS finalize → Cloud Function reads manifest
2. Cloud Function launches Cloud Run Job for step 0 (`sales`)
3. Agent runs, writes outputs, advances manifest
4. Manifest write re-triggers Cloud Function for step 1 (`finance`)
5. Workflow completes

### Step 7: Monitor Execution

```bash
# Cloud Function logs
gcloud functions logs read \
  $(terraform output -raw cloud_function_name) \
  --region $(terraform output -raw gcp_region 2>/dev/null || echo us-central1) \
  --gen2 --limit 50

# Cloud Run Job executions
gcloud run jobs executions list \
  --job $(terraform output -raw cloud_run_job_name) \
  --region us-central1

# Cloud Run Job logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=$(terraform output -raw cloud_run_job_name)" \
  --limit 50 --format="table(timestamp,textPayload)"

# Check workflow status
gsutil cat gs://${BUCKET}/runs/run_001/manifest.json | python -m json.tool
```

---

## Terraform Variables Reference

| Variable | Type | Default | Required | Description |
|----------|------|---------|:--------:|-------------|
| `gcp_project` | `string` | — | **Yes** | GCP project ID |
| `gcp_region` | `string` | `us-central1` | No | GCP region for all resources |
| `environment` | `string` | `dev` | No | Environment name (used in resource naming) |
| `project_name` | `string` | `agent-workflow-engine` | No | Prefix for all resource names |
| `anthropic_api_key` | `string` | `""` | Conditional | Required if `agent_runtime = "claude"` |
| `openai_api_key` | `string` | `""` | Conditional | Required if `agent_runtime = "codex"` |
| `agent_image_tag` | `string` | `latest` | No | Docker image tag in Artifact Registry |
| `container_cpu` | `string` | `"1"` | No | Cloud Run Job CPU limit |
| `container_memory` | `string` | `"4Gi"` | No | Cloud Run Job memory limit |
| `bucket_name` | `string` | `""` | No | Override auto-generated bucket name |
| `agent_runtime` | `string` | `"claude"` | No | Runtime backend: `claude`, `codex`, `deepagent`, `echo` |
| `llm_model` | `string` | `""` | No | LLM model override (e.g., `openai:gpt-5`) |

---

## Terraform Outputs

| Output | Description |
|--------|-------------|
| `bucket_name` | GCS workflow bucket name |
| `artifact_registry_url` | Docker image path prefix for pushing |
| `cloud_run_job_name` | Cloud Run Job resource name |
| `cloud_function_name` | Cloud Function resource name |
| `docker_push_commands` | Copy-paste commands for building/pushing the agent image |
| `trigger_workflow_command` | Copy-paste command to trigger a sample workflow |

---

## File Structure

```
infra/gcp/
├── main.tf                 # Terraform config, providers, required versions
├── variables.tf            # All input variables with defaults
├── outputs.tf              # Terraform outputs
├── apis.tf                 # GCP API enablement (8 services)
├── gcs.tf                  # GCS workflows bucket (versioned, lifecycle rules)
├── artifact_registry.tf    # Docker image registry (cleanup policy)
├── cloud_run_job.tf        # Agent container job definition
├── cloud_function.tf       # Event-driven router function
├── secrets.tf              # Secret Manager for API keys
├── iam.tf                  # Service accounts + IAM bindings
├── function/               # Cloud Function source code
│   ├── main.py             # Event handler (GCS → manifest → Cloud Run Job)
│   └── requirements.txt    # Python dependencies
├── README.md               # Quick-start guide
├── README_GCP.md           # This file — comprehensive deployment guide
└── .gitignore              # Ignores .terraform/, *.tfvars, *.tfstate
```

---

## Security Notes

### Current State (Phase 1 — MVP)

- Service accounts use broad `roles/storage.objectAdmin` for rapid iteration.
- API keys stored in Secret Manager with `latest` version pinning.
- All resources labeled with `managed_by = terraform`.

### Phase 2 Hardening (TODO)

- [ ] Tighten IAM: `roles/storage.objectAdmin` → `roles/storage.objectViewer` + `roles/storage.objectCreator`
- [ ] Pin secret versions instead of using `latest`
- [ ] Enable VPC Service Controls around the GCS bucket
- [ ] Add Cloud Armor / WAF for the Cloud Function HTTP endpoint
- [ ] Move Terraform state to a GCS backend with state locking
- [ ] Enable audit logging on Secret Manager access
- [ ] Add `prevent_destroy` lifecycle rules on production buckets

---

## Cost Estimate (Dev Environment)

| Service | Estimated Monthly Cost | Notes |
|---------|----------------------:|-------|
| GCS Storage | < $1 | Workflow manifests are tiny |
| Cloud Functions | < $1 | Event-driven, minimal invocations |
| Cloud Run Jobs | ~$2–10 | Pay-per-use, 1 CPU / 4 GiB |
| Artifact Registry | < $1 | Single image, cleanup policy |
| Secret Manager | < $1 | 2 secrets, infrequent access |
| **Total** | **~$5–15/month** | |

---

## Troubleshooting

### Cloud Function not triggering

```bash
# Verify event trigger is configured
gcloud functions describe $(terraform output -raw cloud_function_name) \
  --region us-central1 --gen2 --format="yaml(eventTrigger)"

# Check Eventarc channel
gcloud eventarc triggers list --location us-central1
```

### Cloud Run Job fails to start

```bash
# Check the job configuration
gcloud run jobs describe $(terraform output -raw cloud_run_job_name) \
  --region us-central1

# Check if the image exists
gcloud artifacts docker images list \
  $(terraform output -raw artifact_registry_url)
```

### Permission denied errors

```bash
# Verify service account bindings
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:agent-workflow-engine" \
  --format="table(bindings.role)"
```

### Destroy all resources

```bash
terraform destroy
# Type "yes" to confirm — this removes ALL provisioned resources
```

---

## Validation Status

```
$ terraform init     → ✓ Success (google ~6.0, archive ~2.0)
$ terraform validate → ✓ "The configuration is valid."
$ terraform fmt      → ✓ All files properly formatted
```

Last validated: April 2026 with Terraform v1.14.8 and Google provider v6.50.0.
