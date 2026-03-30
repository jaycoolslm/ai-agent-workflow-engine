# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A cloud-agnostic, LLM-agnostic workflow engine that chains AI agent containers in linear sequences. Each step runs a single agent container with one set of Agent Skills (SKILL.md). The agent runtime is selectable (Claude Agent SDK, LangChain Deep Agents, or OpenAI Codex). Orchestration state travels as a JSON manifest in object storage ("the bucket is the bus"). Containers are stateless — they read a manifest, do their work, write outputs, advance the manifest, and exit.

## Build and Run

```bash
# Start MinIO (local S3-compatible object store)
docker compose up minio -d

# Run plumbing tests (no API key needed, validates S3 ops + state machine)
python test_plumbing.py

# Build the agent container image
docker compose build agent

# Run with Claude Agent SDK (default, requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
python router.py --bucket workflows --run-prefix runs/run_001 --seed

# Run with LangChain Deep Agents (LLM-agnostic)
export AGENT_RUNTIME=deepagent
export LLM_MODEL=openai:gpt-5          # or anthropic:claude-sonnet-4-6, google:gemini-2.5-pro
python router.py --bucket workflows --run-prefix runs/run_001 --seed

# Run with custom manifest
python router.py --bucket workflows --run-prefix runs/custom_001 --seed-file my-manifest.json

# Cleanup
docker compose down -v
```

MinIO console: http://localhost:9001 (minioadmin / minioadmin)

## Architecture

### Storage Abstraction (`storage/`)

Protocol + Factory + DI pattern. `StorageProtocol` in `storage/protocol.py` defines 9 methods (read_json, write_json, read_bytes, write_bytes, list_keys, copy_prefix, key_exists, download_prefix_to_dir, upload_dir_to_prefix). Backend selected via `STORAGE_BACKEND` env var.

- `storage/s3.py` — Full implementation (boto3). Works with AWS S3 and MinIO.
- `storage/gcs.py` — Full implementation (google-cloud-storage). Works with GCS and fake-gcs-server.
- `storage/azure.py` — Stub (not yet implemented).
- `storage/factory.py` — `get_storage(backend, **kwargs)` returns the right backend.

### Runtime Abstraction (`runtime/`)

Protocol + Factory + DI pattern (same as storage). `AgentRuntimeProtocol` in `runtime/protocol.py` defines one async method: `execute(prompt, skills_dir, output_dir, max_turns) -> str`. Backend selected via `AGENT_RUNTIME` env var.

- `runtime/claude_sdk.py` — Full implementation (Claude Agent SDK). Default. Skills loaded via `.claude/skills/` symlinks.
- `runtime/deep_agents.py` — Full implementation (LangChain Deep Agents). LLM-agnostic. Skills loaded via `SkillsMiddleware`.
- `runtime/codex_sdk.py` — Stub (not yet implemented).
- `runtime/factory.py` — `get_runtime(backend, **kwargs)` returns the right backend.

### Container Lifecycle (`entrypoint.py`)

The agent container entrypoint. On startup: reads manifest from storage, finds its step, downloads input files to `/workspace/input`, builds a prompt, runs the configured agent runtime with the matching Agent Skills loaded, uploads outputs from `/workspace/output`, updates shared context, advances `current_step` in the manifest, exits.

### Router (`router.py`)

Local-only component. Polls MinIO for manifest changes and launches agent containers via `docker run`. In production this is replaced by cloud event triggers (S3->Lambda->ECS, Blob->EventGrid->ContainerApps, GCS->PubSub->CloudRun). This is the ONLY cloud-specific component per provider.

### Manifest Contract

Workflows are defined as JSON manifests stored at `{run_prefix}/manifest.json`. Key fields: `current_step`, `steps[]` (each with `agent`, `instruction`, `status`), `context`. Steps transition: `pending` -> `running` -> `complete`/`failed`. Each step's outputs go to `step_N/output/` and get copied to `step_N+1/input/`.

## Key Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `STORAGE_BACKEND` | Storage provider (s3, gcs, azure) | s3 |
| `AGENT_RUNTIME` | AI runtime backend (claude, deepagent, codex) | claude |
| `LLM_MODEL` | Model for deepagent runtime (provider:model format) | anthropic:claude-sonnet-4-6 |
| `BUCKET` | Bucket/container name | — |
| `RUN_PREFIX` | Path prefix for this workflow run | — |
| `PLUGIN_NAME` | Which skill group to load (sales, finance, etc.) | — |
| `S3_ENDPOINT` | Custom S3 endpoint (for MinIO) | empty (uses AWS) |
| `GCP_PROJECT` | GCP project ID (for gcs backend) | empty (auto-detected on Cloud Run) |
| `STORAGE_EMULATOR_HOST` | GCS emulator endpoint (for fake-gcs-server) | empty (uses GCS) |
| `ANTHROPIC_API_KEY` | Claude API access (required for claude runtime only) | — |

## Agent Skills

Skills use the open [Agent Skills standard](https://agentskills.io/specification) (SKILL.md format). Each skill is a directory containing a `SKILL.md` file with YAML frontmatter (name, description) and markdown instructions. Skills are grouped by domain:

```
skills/
├── sales/
│   └── account-research/SKILL.md
└── finance/
    ├── audit-support/SKILL.md
    └── financial-statements/SKILL.md
```

`PLUGIN_NAME` selects which group is loaded into the agent session. Skills are portable across all supported runtimes and any agent tool that supports the SKILL.md standard (Claude Code, Codex, Copilot, Cursor, and 20+ others).
