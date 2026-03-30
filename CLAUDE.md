# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A cloud-agnostic workflow engine that chains AI agent containers in linear sequences. Each step runs a single Claude Agent SDK container with one knowledge-work plugin (sales, finance, legal, etc.). Orchestration state travels as a JSON manifest in object storage ("the bucket is the bus"). Containers are stateless — they read a manifest, do their work, write outputs, advance the manifest, and exit.

## Build and Run

```bash
# Start MinIO (local S3-compatible object store)
docker compose up minio -d

# Run plumbing tests (no API key needed, validates S3 ops + state machine)
python test_plumbing.py

# Build the agent container image
docker compose build agent

# Run a full workflow (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
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
- `storage/gcs.py` — Stub (not yet implemented).
- `storage/azure.py` — Stub (not yet implemented).
- `storage/factory.py` — `get_storage(backend, **kwargs)` returns the right backend.

### Container Lifecycle (`entrypoint.py`)

The agent container entrypoint. On startup: reads manifest from storage, finds its step, downloads input files to `/workspace/input`, runs Claude Agent SDK with the matching knowledge-work plugin loaded, uploads outputs from `/workspace/output`, updates shared context, advances `current_step` in the manifest, exits. Uses `bypassPermissions` mode with `disallowed_tools` for safety.

### Router (`router.py`)

Local-only component. Polls MinIO for manifest changes and launches agent containers via `docker run`. In production this is replaced by cloud event triggers (S3→Lambda→ECS, Blob→EventGrid→ContainerApps, GCS→PubSub→CloudRun). This is the ONLY cloud-specific component per provider.

### Manifest Contract

Workflows are defined as JSON manifests stored at `{run_prefix}/manifest.json`. Key fields: `current_step`, `steps[]` (each with `agent`, `instruction`, `status`), `context`. Steps transition: `pending` → `running` → `complete`/`failed`. Each step's outputs go to `step_N/output/` and get copied to `step_N+1/input/`.

## Key Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `STORAGE_BACKEND` | Storage provider (s3, gcs, azure) | s3 |
| `BUCKET` | Bucket/container name | — |
| `RUN_PREFIX` | Path prefix for this workflow run | — |
| `PLUGIN_NAME` | Which knowledge-work plugin to load | — |
| `S3_ENDPOINT` | Custom S3 endpoint (for MinIO) | empty (uses AWS) |
| `ANTHROPIC_API_KEY` | Claude API access | — |

## Plugins

Plugins come from [anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins), cloned at Docker build time into `/opt/plugins`. Each plugin has `.claude-plugin/plugin.json` and markdown-based skills. Available: sales, finance, marketing, legal, data, engineering, customer-support, product-management, productivity, enterprise-search, bio-research, and more.
