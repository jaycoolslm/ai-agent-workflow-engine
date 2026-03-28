# Workflow Engine: Local POC

Test the full cloud-agnostic workflow engine locally using Docker and MinIO.

## What's Here

```
workflow-poc/
├── docker-compose.yml      # MinIO + agent image build
├── Dockerfile.agent        # The universal agent container
├── entrypoint.py           # Agent lifecycle (read manifest, run Claude, write outputs)
├── router.py               # Local stand-in for cloud event trigger
├── test_plumbing.py        # Validates all wiring WITHOUT calling Claude
├── sample-manifest.json    # Example 2-step workflow (sales -> finance)
└── README.md               # You are here
```

## Prerequisites

- Docker Desktop running
- Python 3.10+ on your host (for router and tests)
- `pip install boto3` on your host
- An Anthropic API key (only needed for the real run, not the plumbing test)

## Step 1: Validate the Plumbing (No API Key Needed)

This tests S3 operations, manifest state machine, file handover, context
accumulation, and error handling. No Claude calls, no API key, no agent
containers. Just MinIO and Python.

```bash
# Start MinIO
docker compose up minio -d

# Wait a few seconds for it to be ready, then run tests
pip install boto3
python test_plumbing.py
```

You should see all 10 tests pass. You can also open http://localhost:9001
(minioadmin / minioadmin) to browse the bucket contents visually.

## Step 2: Build the Agent Image

```bash
docker compose build agent
```

This bakes in Python 3.12, Node.js 22, the Claude Agent SDK, boto3,
and the full knowledge-work-plugins repo. Takes a few minutes the first
time; subsequent builds use Docker layer caching.

## Step 3: Run a Real Workflow

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Seed a sample workflow and run it
python router.py --bucket workflows --run-prefix runs/run_001 --seed
```

This will:
1. Create the `workflows` bucket in MinIO
2. Upload the sample manifest (sales research on Grab Holdings, then finance audit)
3. Mark step 0 as `running` and launch the `sales` agent container
4. When the sales container finishes, it advances the manifest
5. The router sees step 1 is `pending`, marks it `running`, launches `finance`
6. When finance finishes, the workflow is marked `complete`

Watch the terminal for agent output. Inspect results in MinIO console at
http://localhost:9001.

## Step 4: Run a Custom Workflow

Create your own manifest:

```bash
python router.py \
  --bucket workflows \
  --run-prefix runs/custom_001 \
  --seed-file my-manifest.json
```

Available plugin names (matching knowledge-work-plugins repo):
- sales
- finance
- marketing
- legal
- data
- engineering
- customer-support
- product-management
- productivity
- enterprise-search
- bio-research

## What This Proves

The local POC validates that the architecture works end-to-end:

| Concern                  | Local (MinIO + Docker)         | Production equivalent          |
|--------------------------|-------------------------------|-------------------------------|
| Object store             | MinIO on localhost:9000       | S3 / Blob Storage / GCS      |
| Event trigger            | router.py polling             | S3 Event -> Lambda            |
| Container runtime        | docker run                    | Fargate / Cloud Run / ACA    |
| Manifest state machine   | Identical                     | Identical                     |
| File handover            | S3 copy (identical API)       | S3 copy (identical API)       |
| Agent container          | Same image                    | Same image                    |

The agent container, the entrypoint, the manifest format, and the S3
operations are all identical between local and production. The ONLY
thing that changes is the router implementation (50 lines of glue code
per cloud provider).

## Cleanup

```bash
docker compose down -v    # Stops MinIO, removes data volume
```
