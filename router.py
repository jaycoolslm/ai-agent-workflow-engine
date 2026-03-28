"""
Local Router: simulates the cloud event trigger (S3 event -> Lambda/Function -> container launch).

Polls MinIO for manifest.json changes. When current_step is pending, marks it as running
and launches the appropriate agent container via `docker run`.

This is the ONLY cloud-specific component. In production you replace this with:
  - AWS:   S3 Event -> EventBridge -> Lambda -> ECS RunTask
  - Azure: Blob trigger -> Event Grid -> Function -> Container Apps Job
  - GCP:   GCS notification -> Pub/Sub -> Cloud Function -> Cloud Run Job
  - K8s:   MinIO webhook -> NATS -> controller -> Kubernetes Job

Usage:
    pip install boto3
    python router.py --bucket workflows --run-prefix runs/run_001
"""

import argparse
import json
import os
import subprocess
import sys
import time

import boto3
from botocore.config import Config

# MinIO connection defaults (matches docker-compose)
MINIO_ENDPOINT = os.environ.get("S3_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")

# The agent docker image name (built by docker-compose)
AGENT_IMAGE = os.environ.get("AGENT_IMAGE", "workflow-agent:local")

# Your Anthropic API key
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )


def ensure_bucket(s3, bucket: str):
    try:
        s3.head_bucket(Bucket=bucket)
    except s3.exceptions.ClientError:
        s3.create_bucket(Bucket=bucket)
        print(f"Created bucket: {bucket}")


def read_manifest(s3, bucket: str, prefix: str) -> dict:
    key = f"{prefix}/manifest.json"
    resp = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(resp["Body"].read().decode("utf-8"))


def write_manifest(s3, bucket: str, prefix: str, manifest: dict):
    key = f"{prefix}/manifest.json"
    body = json.dumps(manifest, indent=2, default=str).encode("utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=body)


def launch_agent_container(
    plugin_name: str,
    bucket: str,
    run_prefix: str,
) -> int:
    """
    Launch an agent container via `docker run`. Returns the exit code.

    The container connects to MinIO via the Docker bridge network.
    """
    # MinIO endpoint from inside the container (docker-compose network)
    container_minio_endpoint = "http://host.docker.internal:9000"

    cmd = [
        "docker", "run",
        "--rm",
        "--add-host=host.docker.internal:host-gateway",
        "-e", f"PLUGIN_NAME={plugin_name}",
        "-e", f"BUCKET={bucket}",
        "-e", f"RUN_PREFIX={run_prefix}",
        "-e", f"S3_ENDPOINT={container_minio_endpoint}",
        "-e", f"AWS_ACCESS_KEY_ID={MINIO_ACCESS_KEY}",
        "-e", f"AWS_SECRET_ACCESS_KEY={MINIO_SECRET_KEY}",
        "-e", f"AWS_DEFAULT_REGION=us-east-1",
        "-e", f"ANTHROPIC_API_KEY={ANTHROPIC_API_KEY}",
        AGENT_IMAGE,
    ]

    print(f"\n{'='*60}")
    print(f"LAUNCHING: {plugin_name}")
    print(f"{'='*60}")
    print(f"Command: docker run ... {AGENT_IMAGE}")
    print(f"Plugin: {plugin_name}")
    print(f"Bucket: {bucket}")
    print(f"Prefix: {run_prefix}")
    print()

    result = subprocess.run(cmd)
    return result.returncode


def run_workflow(s3, bucket: str, run_prefix: str):
    """
    Main loop: check manifest, launch containers, repeat until done or failed.
    """
    while True:
        manifest = read_manifest(s3, bucket, run_prefix)

        # Check for terminal states
        if manifest.get("status") in ("complete", "failed"):
            print(f"\n{'='*60}")
            print(f"WORKFLOW {manifest['status'].upper()}")
            print(f"{'='*60}")
            print(json.dumps(manifest, indent=2))
            return manifest["status"] == "complete"

        step_idx = manifest["current_step"]
        step = manifest["steps"][step_idx]

        if step["status"] == "complete":
            # This shouldn't happen in normal flow, but handle it
            print(f"Step {step_idx} already complete, checking next...")
            next_idx = step_idx + 1
            if next_idx >= len(manifest["steps"]):
                manifest["status"] = "complete"
                write_manifest(s3, bucket, run_prefix, manifest)
                continue
            manifest["current_step"] = next_idx
            write_manifest(s3, bucket, run_prefix, manifest)
            continue

        if step["status"] == "running":
            # A previous container may have crashed. Wait a moment and retry.
            print(f"Step {step_idx} is still 'running'. Waiting 5s before retry...")
            time.sleep(5)
            continue

        if step["status"] == "pending":
            # Mark as running and launch
            step["status"] = "running"
            write_manifest(s3, bucket, run_prefix, manifest)

            exit_code = launch_agent_container(
                plugin_name=step["agent"],
                bucket=bucket,
                run_prefix=run_prefix,
            )

            if exit_code != 0:
                print(f"\nContainer exited with code {exit_code}")
                # Re-read manifest to see if the container marked it as failed
                manifest = read_manifest(s3, bucket, run_prefix)
                if manifest.get("status") != "failed":
                    step = manifest["steps"][step_idx]
                    step["status"] = "failed"
                    step["error"] = f"Container exited with code {exit_code}"
                    manifest["status"] = "failed"
                    write_manifest(s3, bucket, run_prefix, manifest)
                return False

        # Small delay before checking the next state
        time.sleep(1)


def seed_workflow(s3, bucket: str, run_prefix: str, manifest: dict):
    """Upload the initial manifest to kick off a workflow."""
    ensure_bucket(s3, bucket)
    write_manifest(s3, bucket, run_prefix, manifest)
    print(f"Seeded workflow at {bucket}/{run_prefix}/manifest.json")


def main():
    parser = argparse.ArgumentParser(description="Local workflow router")
    parser.add_argument("--bucket", default="workflows", help="S3 bucket name")
    parser.add_argument("--run-prefix", default="runs/run_001", help="Run prefix in bucket")
    parser.add_argument(
        "--seed", action="store_true",
        help="Seed a sample workflow before running"
    )
    parser.add_argument(
        "--seed-file", type=str, default="",
        help="Path to a custom manifest.json to seed"
    )
    args = parser.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)

    s3 = get_s3_client()

    if args.seed or args.seed_file:
        if args.seed_file:
            with open(args.seed_file) as f:
                manifest = json.load(f)
        else:
            # Default sample: sales research -> finance audit
            manifest = {
                "run_id": "run_001",
                "workflow": "company-assessment",
                "created_at": "2026-03-28T10:00:00Z",
                "status": "running",
                "current_step": 0,
                "steps": [
                    {
                        "step": 0,
                        "agent": "sales",
                        "instruction": (
                            "Research the company 'Grab Holdings' (GRAB). "
                            "Find their latest revenue figures, key business segments, "
                            "recent news, and competitive position in Southeast Asia. "
                            "Output a structured company profile as company_profile.md "
                            "and a JSON summary as company_data.json."
                        ),
                        "status": "pending",
                    },
                    {
                        "step": 1,
                        "agent": "finance",
                        "instruction": (
                            "Using the company profile and data from the previous step, "
                            "perform a financial health assessment. Analyze revenue trends, "
                            "profitability, debt levels, and cash flow. Score the company "
                            "on a 1-10 scale across: revenue growth, profitability, "
                            "balance sheet strength, and cash generation. "
                            "Output an audit report as financial_audit.md "
                            "and a scorecard as scorecard.json."
                        ),
                        "status": "pending",
                    },
                ],
                "context": {
                    "company_name": "Grab Holdings",
                    "ticker": "GRAB",
                    "region": "Southeast Asia",
                    "requested_by": "jake@plazatech.co",
                },
            }

        seed_workflow(s3, args.bucket, args.run_prefix, manifest)

    print(f"\n{'='*60}")
    print(f"WORKFLOW ROUTER")
    print(f"{'='*60}")
    print(f"Bucket:   {args.bucket}")
    print(f"Prefix:   {args.run_prefix}")
    print(f"MinIO:    {MINIO_ENDPOINT}")
    print(f"Image:    {AGENT_IMAGE}")
    print()

    success = run_workflow(s3, args.bucket, args.run_prefix)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
