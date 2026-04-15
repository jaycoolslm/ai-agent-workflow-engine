# AI Agent Workflow Engine

Cloud-agnostic, LLM-agnostic workflow engine that chains AI agent containers in linear sequences. Each step runs a stateless container with domain-specific Agent Skills (SKILL.md). Orchestration state travels as a JSON manifest in object storage — **"the bucket is the bus."**

> **Rust V2 now available** — a complete Rust rewrite lives in [`rust-orchestrator/`](rust-orchestrator/). 27x less memory, 16x faster cold start, production-grade benchmarks and evaluation. See [Performance: Python vs Rust](#performance-python-vs-rust) below.

## What's Here

```
workflow-engine/
├── docker-compose.yml          # MinIO + Azurite + agent image build
├── docker-compose.nfs.yml      # NFS server + agent with S3 Files mount
├── docker-compose.gcs.yml      # fake-gcs-server variant
├── Dockerfile.agent            # The universal agent container
├── entrypoint.py               # Agent lifecycle (read manifest, run agent, write outputs)
├── router.py                   # Local stand-in for cloud event trigger
├── storage/                    # Cloud-agnostic storage abstraction
│   ├── protocol.py             # StorageProtocol interface
│   ├── factory.py              # Backend factory (s3, gcs, azure, nfs)
│   ├── s3.py                   # AWS S3 / MinIO backend
│   ├── gcs.py                  # Google Cloud Storage backend
│   ├── azure.py                # Azure Blob Storage backend
│   └── nfs.py                  # [NEW] Amazon S3 Files NFS mount backend
├── runtime/                    # LLM-agnostic agent runtime abstraction
│   ├── protocol.py             # AgentRuntimeProtocol interface
│   ├── factory.py              # Backend factory (claude, deepagent, codex, openharness)
│   ├── claude_sdk.py           # Claude Agent SDK runtime
│   ├── deep_agents.py          # LangChain Deep Agents runtime
│   ├── codex_sdk.py            # Codex runtime (stub)
│   └── openharness.py          # [NEW] OpenHarness agent runtime
├── evaluation/                 # [NEW] AI output quality evaluation
│   └── __init__.py             # Hallucination detection, completeness checks
├── openharness/                # [NEW] Node.js deps for OpenHarness runtime
│   └── package.json            # @openharness/core + AI SDK providers
├── skills/                     # Agent skill definitions (SKILL.md format)
├── infra/                      # Cloud deployment (AWS/Azure/GCP Terraform)
├── test_plumbing.py            # S3 plumbing test (MinIO)
├── test_plumbing_nfs.py        # [NEW] NFS storage backend test
├── test_openharness_runtime.py # [NEW] OpenHarness runtime test
├── test_evaluation.py          # [NEW] AI evaluation module test
├── test_integration.py         # [NEW] Full integration test
├── sample-manifest.json        # Example 2-step workflow
└── README.md                   # You are here
```

## Prerequisites

- Docker Desktop running
- Python 3.10+ on your host (for router and tests)
- `pip install boto3` on your host
- An Anthropic API key (only needed for Claude runtime, not plumbing tests)

## Architecture

### Storage Backends

| Backend | Use Case | Env Vars |
|---------|----------|----------|
| `s3` (default) | AWS S3, MinIO, any S3-compatible | `STORAGE_BACKEND=s3 S3_ENDPOINT=...` |
| `nfs` **NEW** | Amazon S3 Files NFS mount | `STORAGE_BACKEND=nfs NFS_MOUNT_PATH=/mnt/s3` |
| `gcs` | Google Cloud Storage | `STORAGE_BACKEND=gcs GCP_PROJECT=...` |
| `azure` | Azure Blob Storage | `STORAGE_BACKEND=azure AZURE_STORAGE_CONNECTION_STRING=...` |

### Agent Runtimes

| Runtime | Use Case | Env Vars |
|---------|----------|----------|
| `claude` (default) | Claude Agent SDK | `AGENT_RUNTIME=claude ANTHROPIC_API_KEY=...` |
| `openharness` **NEW** | OpenHarness (LLM-agnostic) | `AGENT_RUNTIME=openharness LLM_MODEL=gpt-4o OPENHARNESS_PROVIDER=openai` |
| `deepagent` | LangChain Deep Agents | `AGENT_RUNTIME=deepagent LLM_MODEL=openai:gpt-4o` |
| `codex` | Codex SDK (stub) | `AGENT_RUNTIME=codex` |

### Data Flow: S3 Copy vs NFS Mount

**Before (S3 Copy — high latency):**
```
Agent A → write output → S3 PutObject → S3 CopyObject → S3 GetObject → Agent B reads
         (upload)        (copy in S3)     (download)
```

**After (S3 Files NFS — zero latency):**
```
Agent A → write to /mnt/s3/step_0/output/ → Agent B reads /mnt/s3/step_1/input/
         (local filesystem write)            (local filesystem read, or symlink)
```

## Step 1: Run Tests (No API Key Needed)

### NFS Storage Test (no Docker needed)
```bash
python test_plumbing_nfs.py
```

### OpenHarness Runtime Test (no Docker needed)
```bash
python test_openharness_runtime.py
```

### AI Evaluation Test (no Docker needed)
```bash
python test_evaluation.py
```

### Full Integration Test (no Docker needed)
```bash
python test_integration.py
```

### Original S3 Plumbing Test (needs MinIO)
```bash
docker compose up minio -d
pip install boto3
python test_plumbing.py
```

## Step 2: Build the Agent Image

```bash
docker compose build agent
```

This bakes in Python 3.12, Node.js 22, the Claude Agent SDK,
OpenHarness core, boto3, and all AI SDK providers.

## Step 3: Run a Real Workflow

### With Claude (default)
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python router.py --bucket workflows --run-prefix runs/run_001 --seed
```

### With OpenHarness (OpenAI)
```bash
export OPENAI_API_KEY=sk-...
AGENT_RUNTIME=openharness LLM_MODEL=gpt-4o python router.py \
  --bucket workflows --run-prefix runs/run_001 --seed
```

### With NFS Storage
```bash
# Start NFS server
docker compose -f docker-compose.nfs.yml up nfs-server -d

# Run with NFS backend
STORAGE_BACKEND=nfs NFS_MOUNT_PATH=/mnt/s3 python router.py \
  --bucket workflows --run-prefix runs/run_001 --seed
```

## What This Proves

| Concern                  | Local (MinIO + Docker)         | Production equivalent          |
|--------------------------|-------------------------------|-------------------------------|
| Object store             | MinIO on localhost:9000       | S3 / Blob Storage / GCS      |
| Object store (NFS)       | Local temp dir / NFS server   | Amazon S3 Files NFS Mount    |
| Event trigger            | router.py polling             | S3 Event -> Lambda            |
| Container runtime        | docker run                    | Fargate / Cloud Run / ACA    |
| Manifest state machine   | Identical                     | Identical                     |
| File handover (S3)       | S3 copy (identical API)       | S3 copy (identical API)       |
| File handover (NFS)      | Local copy / symlink          | NFS copy / symlink            |
| Agent runtime            | Claude / OpenHarness          | Claude / OpenHarness          |
| Output evaluation        | Offline evaluator             | Offline evaluator             |
| Agent container          | Same image                    | Same image                    |

## Cleanup

```bash
docker compose down -v    # Stops MinIO, removes data volume
```

## Cloud Deployment

- **[AWS deployment guide](infra/aws/README.md)** — Deploy to AWS with Terraform (S3 + Lambda + ECS Fargate)
- **[GCP deployment guide](infra/gcp/README.md)** — Deploy to GCP with Terraform (GCS + Cloud Functions + Cloud Run Jobs)
- **Azure** — Terraform modules in `infra/azure/` (Blob + EventGrid + Container Apps)

---

## Rust V2: `rust-orchestrator/`

A complete rewrite in Rust for production workloads. Same architecture, same manifest contract, same skills — dramatically better resource efficiency.

### Performance: Python vs Rust

| Metric | Python (this dir) | Rust (`rust-orchestrator/`) | Improvement |
|--------|-------------------|----------------------------|-------------|
| **Memory (RSS)** | 219 MB | 8 MB | **27x** |
| **Cold Start** | 848 ms | 53 ms | **16x** |
| **Docker Image** | 1.34 GB | 629 MB | **2.1x** |
| **Test Suite** | 7 test files | 40 tests in 0.16s | Consolidated |
| **I/O (100 MB)** | 92 ms write, 78 ms read | 157 ms write, 77 ms read | Disk-bound (equal) |

### AWS Cost Impact (ECS Fargate, 10K Runs/Month)

| Component | Python | Rust | Savings |
|-----------|--------|------|---------|
| Fargate Memory | $2.96/mo (2 GB needed) | $0.74/mo (0.5 GB enough) | **75%** |
| Total Infra | $17.00/mo | $14.78/mo | **13%** |

At **1M runs/month**: $849 → $738 (**$1,332/yr savings**).

At **10K concurrent agents on EC2**: Python needs 18× `r7i.4xlarge` ($10,534/mo) vs Rust needs 1 instance ($585/mo) — **94% cost reduction**.

### When to Use Which

| Scenario | Recommendation |
|----------|---------------|
| Prototyping / small scale (<1K runs/mo) | **Python** — faster iteration, more familiar |
| Production / cost-sensitive | **Rust** — 27x memory efficiency, 16x cold start |
| Self-hosted / high density | **Rust** — 16,000 agents per instance vs 580 |
| Custom runtimes needed | **Python** — Claude SDK + LangChain Deep Agents available |
| Codex / OpenHarness runtimes | **Either** — both implement these runtimes |

### Quick Start (Rust)

```bash
cd rust-orchestrator
cargo build --release
cargo test          # 40 tests, no API keys needed
cargo run --release --bin router -- --bucket workflows --run-prefix runs/run_001 --seed
```

Full documentation: [`rust-orchestrator/README.md`](rust-orchestrator/README.md)

---

## What's Here (Python)
