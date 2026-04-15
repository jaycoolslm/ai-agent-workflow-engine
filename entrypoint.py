"""
Workflow agent container entrypoint.

Reads manifest from object storage, loads the assigned Agent Skills (SKILL.md),
executes the step via the configured runtime (Claude SDK, Deep Agents, or Codex),
writes outputs back, advances the manifest.

Storage backend is selected via STORAGE_BACKEND env var (s3, gcs, azure).
Agent runtime is selected via AGENT_RUNTIME env var (claude, deepagent, codex).
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from storage import get_storage
from storage.protocol import StorageProtocol
from storage_provider import get_storage_provider, StorageProvider
from runtime import get_runtime
from runtime.protocol import AgentRuntimeProtocol

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
BUCKET = os.environ.get("BUCKET", "")
RUN_PREFIX = os.environ.get("RUN_PREFIX", "")
PLUGIN_NAME = os.environ.get("PLUGIN_NAME", "")
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "s3")
STORAGE_MODE = os.environ.get("STORAGE_MODE", "")  # 's3' or 'direct_mount'
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")  # e.g. http://minio:9000
GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
AZURE_CONNECTION_STRING = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
NFS_MOUNT_PATH = os.environ.get("NFS_MOUNT_PATH", "/mnt/s3")  # S3 Files NFS mount
AGENT_RUNTIME = os.environ.get("AGENT_RUNTIME", "claude")
SKILLS_ROOT = Path("/opt/skills")
WORKSPACE = Path("/workspace")


# ---------------------------------------------------------------------------
# Skills resolution
# ---------------------------------------------------------------------------
def resolve_skills_dir(plugin_name: str) -> Path | None:
    """Resolve PLUGIN_NAME to a skills directory containing SKILL.md subdirs."""
    candidate = SKILLS_ROOT / plugin_name
    if not candidate.exists():
        available = [
            p.name
            for p in SKILLS_ROOT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ] if SKILLS_ROOT.exists() else []
        print(f"WARNING: Skills directory '{plugin_name}' not found at {SKILLS_ROOT}.")
        print(f"Available: {available}")
        print(f"Continuing without skills.")
        return None
    return candidate


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------
def build_prompt(
    instruction: str,
    input_dir: Path,
    output_dir: Path,
    context: dict,
) -> str:
    """Build the full agent prompt from workflow step data."""
    input_files = (
        [str(p.relative_to(input_dir)) for p in input_dir.rglob("*") if p.is_file()]
        if input_dir.exists()
        else []
    )

    prompt_parts = [
        f"## Your Task\n{instruction}",
        f"\n## Shared Context\n```json\n{json.dumps(context, indent=2)}\n```",
    ]
    if input_files:
        prompt_parts.append(
            f"\n## Input Files (in {input_dir})\n"
            + "\n".join(f"- {f}" for f in input_files)
        )
    prompt_parts.append(f"\n## Output\nWrite all output files to: {output_dir}\n")
    return "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# Storage factory (composition root)
# ---------------------------------------------------------------------------
def _create_storage() -> StorageProtocol:
    if STORAGE_BACKEND == "s3":
        return get_storage("s3", bucket=BUCKET, endpoint_url=S3_ENDPOINT)
    if STORAGE_BACKEND == "gcs":
        return get_storage("gcs", bucket=BUCKET, project=GCP_PROJECT)
    if STORAGE_BACKEND == "azure":
        return get_storage("azure", container=BUCKET, connection_string=AZURE_CONNECTION_STRING)
    if STORAGE_BACKEND == "nfs":
        return get_storage("nfs", bucket=BUCKET, mount_path=NFS_MOUNT_PATH)
    raise ValueError(f"Unknown STORAGE_BACKEND: {STORAGE_BACKEND}")


def _create_storage_provider() -> StorageProvider | None:
    """Create an optional StorageProvider for file-level operations.

    When STORAGE_MODE is set (e.g. 'direct_mount'), this returns a
    high-performance provider that bypasses the boto3 API pipeline. When
    unset, returns None and the classic StorageProtocol path is used.
    """
    if not STORAGE_MODE:
        return None
    return get_storage_provider(
        mode=STORAGE_MODE,
        bucket=BUCKET,
        endpoint_url=S3_ENDPOINT,
        mount_path=NFS_MOUNT_PATH,
    )


# ---------------------------------------------------------------------------
# Runtime factory (composition root)
# ---------------------------------------------------------------------------
def _create_runtime() -> AgentRuntimeProtocol:
    if AGENT_RUNTIME == "claude":
        return get_runtime("claude")
    if AGENT_RUNTIME == "deepagent":
        model = os.environ.get("LLM_MODEL", "")
        return get_runtime("deepagent", model=model)
    if AGENT_RUNTIME == "codex":
        model = os.environ.get("CODEX_MODEL", os.environ.get("LLM_MODEL", "gpt-4.1"))
        return get_runtime("codex", model=model)
    if AGENT_RUNTIME == "openharness":
        model = os.environ.get("LLM_MODEL", "gpt-4o")
        provider = os.environ.get("OPENHARNESS_PROVIDER", "openai")
        return get_runtime("openharness", model=model, provider=provider)
    if AGENT_RUNTIME == "echo":
        return get_runtime("echo")
    raise ValueError(f"Unknown AGENT_RUNTIME: {AGENT_RUNTIME}")


# ---------------------------------------------------------------------------
# Main lifecycle
# ---------------------------------------------------------------------------
async def main():
    if not PLUGIN_NAME:
        print("ERROR: PLUGIN_NAME is required")
        sys.exit(1)
    if AGENT_RUNTIME == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is required for claude runtime")
        sys.exit(1)
    if AGENT_RUNTIME == "codex" and not os.environ.get("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY is required for codex runtime")
        sys.exit(1)
    if not BUCKET or not RUN_PREFIX:
        print("ERROR: BUCKET and RUN_PREFIX are required")
        sys.exit(1)

    storage = _create_storage()
    provider = _create_storage_provider()
    runtime = _create_runtime()
    skills_dir = resolve_skills_dir(PLUGIN_NAME)

    print(f"=== Agent Container ===")
    print(f"Plugin:     {PLUGIN_NAME}")
    print(f"Runtime:    {AGENT_RUNTIME}")
    print(f"Backend:    {STORAGE_BACKEND}")
    if STORAGE_MODE:
        print(f"Mode:       {STORAGE_MODE} (StorageProvider)")
    print(f"Bucket:     {BUCKET}")
    print(f"Run prefix: {RUN_PREFIX}")
    if skills_dir:
        print(f"Skills dir: {skills_dir}")
    if S3_ENDPOINT:
        print(f"S3 endpoint: {S3_ENDPOINT}")
    if GCP_PROJECT:
        print(f"GCP project: {GCP_PROJECT}")
    print()

    # 1. Read manifest
    manifest = storage.read_json(f"{RUN_PREFIX}/manifest.json")
    step_idx = manifest["current_step"]
    step = manifest["steps"][step_idx]

    if step["agent"] != PLUGIN_NAME:
        print(f"ERROR: Expected agent '{step['agent']}', got '{PLUGIN_NAME}'")
        sys.exit(1)
    if step["status"] != "running":
        print(f"ERROR: Step status is '{step['status']}', expected 'running'")
        sys.exit(1)

    print(f"Step {step_idx}: {step['agent']}")
    print(f"Instruction: {step['instruction']}")
    print()

    # 2. Read shared context
    context = {}
    context_key = f"{RUN_PREFIX}/context.json"
    if storage.key_exists(context_key):
        context = storage.read_json(context_key)

    # 3. Download input files to local workspace
    input_dir = WORKSPACE / "input"
    output_dir = WORKSPACE / "output"
    for d in [input_dir, output_dir]:
        if d.exists():
            import shutil

            shutil.rmtree(d)
        d.mkdir(parents=True)

    step_input_prefix = f"{RUN_PREFIX}/step_{step_idx}/input"
    storage.download_prefix_to_dir(step_input_prefix, input_dir)

    # 4. Build prompt and run the agent
    prompt = build_prompt(step["instruction"], input_dir, output_dir, context)

    try:
        agent_output = await runtime.execute(
            prompt=prompt,
            skills_dir=skills_dir,
            output_dir=output_dir,
        )

        # 5. Upload outputs
        step_output_prefix = f"{RUN_PREFIX}/step_{step_idx}/output"
        storage.upload_dir_to_prefix(output_dir, step_output_prefix)

        # 6. Update shared context
        output_files = [
            str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file()
        ]
        context[f"step_{step_idx}"] = {
            "agent": PLUGIN_NAME,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": (agent_output[:2000] if agent_output else ""),
            "output_files": output_files,
        }
        storage.write_json(context_key, context)

        # 7. Advance the manifest
        step["status"] = "complete"
        step["completed_at"] = datetime.now(timezone.utc).isoformat()

        next_idx = step_idx + 1
        if next_idx < len(manifest["steps"]):
            manifest["current_step"] = next_idx
            next_step = manifest["steps"][next_idx]

            # Determine which steps to pull inputs from
            inputs_from = next_step.get("inputs_from", None)
            if inputs_from is None:
                # Default: previous step only
                inputs_from = [step_idx]

            for prior_idx in inputs_from:
                storage.copy_prefix(
                    f"{RUN_PREFIX}/step_{prior_idx}/output/",
                    f"{RUN_PREFIX}/step_{next_idx}/input/",
                )
        else:
            manifest["status"] = "complete"
            manifest["completed_at"] = datetime.now(timezone.utc).isoformat()

        storage.write_json(f"{RUN_PREFIX}/manifest.json", manifest)
        print(f"\n=== Step {step_idx} COMPLETE ===")

    except Exception as e:
        step["status"] = "failed"
        step["error"] = str(e)
        step["failed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["status"] = "failed"
        storage.write_json(f"{RUN_PREFIX}/manifest.json", manifest)
        print(f"\n=== Step {step_idx} FAILED: {e} ===")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
