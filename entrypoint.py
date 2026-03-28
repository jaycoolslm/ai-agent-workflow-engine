"""
Workflow agent container entrypoint.

Reads manifest from S3 (or MinIO), loads the assigned knowledge-work plugin,
executes the step via Claude Agent SDK, writes outputs back, advances the manifest.

Works identically against MinIO (local) and real S3/GCS/Azure Blob (production).
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import boto3
from botocore.config import Config

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
BUCKET = os.environ.get("BUCKET", "")
RUN_PREFIX = os.environ.get("RUN_PREFIX", "")
PLUGIN_NAME = os.environ.get("PLUGIN_NAME", "")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")  # e.g. http://minio:9000
PLUGINS_ROOT = Path("/opt/plugins")
WORKSPACE = Path("/workspace")


# ---------------------------------------------------------------------------
# S3 storage layer (works with MinIO, AWS S3, any S3-compatible store)
# ---------------------------------------------------------------------------
class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str = ""):
        kwargs = {
            "config": Config(signature_version="s3v4"),
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
            # MinIO needs path-style addressing
            kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )

        self.s3 = boto3.client("s3", **kwargs)
        self.bucket = bucket

    def read_json(self, key: str) -> dict:
        resp = self.s3.get_object(Bucket=self.bucket, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))

    def write_json(self, key: str, data: dict):
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body)

    def write_bytes(self, key: str, data: bytes):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def read_bytes(self, key: str) -> bytes:
        resp = self.s3.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def copy_prefix(self, src_prefix: str, dst_prefix: str):
        for key in self.list_keys(src_prefix):
            new_key = dst_prefix + key[len(src_prefix):]
            self.s3.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": key},
                Key=new_key,
            )

    def key_exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.s3.exceptions.ClientError:
            return False

    def download_prefix_to_dir(self, prefix: str, local_dir: Path):
        """Download all files under a prefix to a local directory."""
        for key in self.list_keys(prefix):
            rel = key[len(prefix):].lstrip("/")
            if not rel:
                continue
            local_path = local_dir / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, key, str(local_path))

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str):
        """Upload all files in a local directory to an S3 prefix."""
        for local_path in local_dir.rglob("*"):
            if local_path.is_file():
                rel = local_path.relative_to(local_dir)
                key = f"{prefix}/{rel}"
                self.s3.upload_file(str(local_path), self.bucket, key)


# ---------------------------------------------------------------------------
# Plugin resolution
# ---------------------------------------------------------------------------
def resolve_plugin_path(plugin_name: str) -> Path:
    candidate = PLUGINS_ROOT / plugin_name
    if not candidate.exists():
        available = [
            p.name for p in PLUGINS_ROOT.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        ]
        print(f"ERROR: Plugin '{plugin_name}' not found.")
        print(f"Available: {available}")
        sys.exit(1)
    return candidate


# ---------------------------------------------------------------------------
# Bash safety guard (PreToolUse hook)
# ---------------------------------------------------------------------------
DANGEROUS_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "dd if=",
    "mkfs",
    "> /dev/",
    "chmod -R 777 /",
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    ":(){:|:&};:",  # fork bomb
]

async def guard_bash(input_data, tool_use_id, context):
    """Block dangerous Bash commands while allowing legitimate ones."""
    if input_data.get("tool_name") == "Bash":
        cmd = input_data.get("tool_input", {}).get("command", "")
        for pattern in DANGEROUS_PATTERNS:
            if pattern in cmd:
                print(f"  [BLOCKED] Bash command matched dangerous pattern: {pattern}")
                print(f"  [BLOCKED] Full command: {cmd[:200]}")
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": f"Blocked dangerous pattern: {pattern}",
                    }
                }
    return {}


async def log_tool_usage(input_data, tool_use_id, context):
    """Log every tool invocation for observability."""
    tool_name = input_data.get("tool_name", "unknown")
    tool_input = input_data.get("tool_input", {})

    if tool_name == "Skill":
        print(f"  [SKILL INVOKED] {json.dumps(tool_input, indent=2)}")
    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")
        print(f"  [BASH] {cmd[:150]}")
    elif tool_name in ("Read", "Write", "Edit"):
        path = tool_input.get("file_path", "")
        print(f"  [{tool_name.upper()}] {path}")
    elif tool_name in ("WebSearch", "WebFetch"):
        query_or_url = tool_input.get("query", tool_input.get("url", ""))
        print(f"  [{tool_name.upper()}] {query_or_url[:150]}")
    else:
        print(f"  [TOOL] {tool_name}")

    return {}


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------
async def run_agent(
    instruction: str,
    plugin_path: Path,
    input_dir: Path,
    output_dir: Path,
    context: dict,
) -> str:
    from claude_agent_sdk import (
        query,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        HookMatcher,
        ToolUseBlock,
        TextBlock,
    )
    # Build prompt
    input_files = [
        str(p.relative_to(input_dir))
        for p in input_dir.rglob("*") if p.is_file()
    ] if input_dir.exists() else []

    prompt_parts = [
        f"## Your Task\n{instruction}",
        f"\n## Shared Context\n```json\n{json.dumps(context, indent=2)}\n```",
    ]
    if input_files:
        prompt_parts.append(
            f"\n## Input Files (in {input_dir})\n"
            + "\n".join(f"- {f}" for f in input_files)
        )
    prompt_parts.append(
        f"\n## Output\nWrite all output files to: {output_dir}\n"
    )
    full_prompt = "\n".join(prompt_parts)

    # Determine plugin load path
    if (plugin_path / ".claude-plugin").exists():
        plugin_load_path = str(plugin_path)
    else:
        plugin_load_path = str(PLUGINS_ROOT)

    print(f"\n--- Agent Config ---")
    print(f"  Plugin path: {plugin_load_path}")
    print(f"  Working dir: {output_dir}")
    print(f"  Permission mode: bypassPermissions")
    print(f"  Disallowed tools: ComputerUse, NotebookEdit")
    print(f"--------------------\n")

    collected = []

    async for message in query(
        prompt=full_prompt,
        options=ClaudeAgentOptions(
            permission_mode="bypassPermissions",
            disallowed_tools=["ComputerUse", "NotebookEdit"],
            setting_sources=["project"],
            plugins=[{"type": "local", "path": plugin_load_path}],
            cwd=str(output_dir),
            max_turns=30,
            # hooks={
            #     "PreToolUse": [
            #         HookMatcher(matcher="Bash", hooks=[guard_bash]),
            #         HookMatcher(hooks=[log_tool_usage]),
            #     ],
            # },
        ),
    ):
        # --- System messages (init, plugin loading, etc) ---
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                plugins = message.data.get("plugins", [])
                commands = message.data.get("slash_commands", [])
                print(f"  [INIT] Plugins loaded: {len(plugins)}")
                for p in plugins:
                    print(f"         - {p.get('name', 'unknown')} ({p.get('path', '')})")
                print(f"  [INIT] Slash commands: {len(commands)}")
                for cmd in commands:
                    if ":" in str(cmd):  # plugin-namespaced commands
                        print(f"         - {cmd}")
            else:
                print(f"  [SYSTEM:{message.subtype}] {json.dumps(message.data, default=str)[:200]}")

        # --- Assistant messages (text, tool calls) ---
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    collected.append(block.text)
                    print(block.text, flush=True)
                elif isinstance(block, ToolUseBlock):
                    if block.name == "Skill":
                        print(f"  [SKILL CALL] {json.dumps(block.input)[:300]}", flush=True)
                    elif block.name == "Bash":
                        print(f"  [BASH] {block.input.get('command', '')[:150]}", flush=True)
                    elif block.name in ("Read", "Write", "Edit"):
                        print(f"  [{block.name.upper()}] {block.input.get('file_path', '')}", flush=True)
                    elif block.name in ("WebSearch", "WebFetch"):
                        print(f"  [{block.name.upper()}] {block.input.get('query', block.input.get('url', ''))[:150]}", flush=True)
                    else:
                        print(f"  [TOOL] {block.name}: {json.dumps(block.input)[:200]}", flush=True)

        # --- Result message (final) ---
        elif isinstance(message, ResultMessage):
            print(f"\n  [RESULT] subtype={message.subtype}")
            print(f"  [RESULT] turns={message.num_turns}")
            print(f"  [RESULT] duration={message.duration_ms}ms")
            if message.total_cost_usd is not None:
                print(f"  [RESULT] cost=${message.total_cost_usd:.4f}")
            if message.usage:
                print(f"  [RESULT] tokens in={message.usage.get('input_tokens', 0)} out={message.usage.get('output_tokens', 0)}")

    return "\n".join(collected)


# ---------------------------------------------------------------------------
# Main lifecycle
# ---------------------------------------------------------------------------
async def main():
    if not PLUGIN_NAME:
        print("ERROR: PLUGIN_NAME is required")
        sys.exit(1)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is required")
        sys.exit(1)
    if not BUCKET or not RUN_PREFIX:
        print("ERROR: BUCKET and RUN_PREFIX are required")
        sys.exit(1)

    storage = S3Storage(BUCKET, endpoint_url=S3_ENDPOINT)
    plugin_path = resolve_plugin_path(PLUGIN_NAME)

    print(f"=== Agent Container ===")
    print(f"Plugin:     {PLUGIN_NAME}")
    print(f"Bucket:     {BUCKET}")
    print(f"Run prefix: {RUN_PREFIX}")
    print(f"S3 endpoint: {S3_ENDPOINT or 'default (AWS)'}")
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

    # 4. Run the agent
    try:
        agent_output = await run_agent(
            instruction=step["instruction"],
            plugin_path=plugin_path,
            input_dir=input_dir,
            output_dir=output_dir,
            context=context,
        )

        # 5. Upload outputs to S3
        step_output_prefix = f"{RUN_PREFIX}/step_{step_idx}/output"
        storage.upload_dir_to_prefix(output_dir, step_output_prefix)

        # 6. Update shared context
        output_files = [
            str(p.relative_to(output_dir))
            for p in output_dir.rglob("*") if p.is_file()
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
            # Copy outputs to next step's inputs
            storage.copy_prefix(
                f"{RUN_PREFIX}/step_{step_idx}/output/",
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
