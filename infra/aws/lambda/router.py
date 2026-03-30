"""
AWS Lambda router: S3 event -> read manifest -> launch ECS Fargate task.

Triggered by S3 PutObject on **/manifest.json. Stateless — no polling loop.
When the container finishes and writes the updated manifest back to S3,
this Lambda is re-triggered and either launches the next step or no-ops.
"""

import json
import os

import boto3

s3 = boto3.client("s3")
ecs = boto3.client("ecs")

CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]
TASK_DEF_ARN = os.environ["TASK_DEFINITION_ARN"]
SUBNET_IDS = json.loads(os.environ["SUBNET_IDS"])
SG_IDS = json.loads(os.environ["SECURITY_GROUP_IDS"])
BUCKET_NAME = os.environ["BUCKET_NAME"]
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "agent")
AGENT_RUNTIME = os.environ.get("AGENT_RUNTIME", "claude")
LLM_MODEL = os.environ.get("LLM_MODEL", "")


def handler(event, context):
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    # Only act on manifest.json files
    if not key.endswith("/manifest.json"):
        print(f"Ignoring non-manifest key: {key}")
        return {"status": "ignored"}

    # Derive run_prefix: "runs/run_001/manifest.json" -> "runs/run_001"
    run_prefix = key.rsplit("/manifest.json", 1)[0]

    # Read manifest
    resp = s3.get_object(Bucket=bucket, Key=key)
    manifest = json.loads(resp["Body"].read().decode("utf-8"))

    # Terminal states — nothing to do
    workflow_status = manifest.get("status", "")
    if workflow_status in ("complete", "failed"):
        print(f"Workflow {workflow_status}. No action.")
        return {"status": workflow_status}

    step_idx = manifest["current_step"]
    step = manifest["steps"][step_idx]
    step_status = step["status"]

    # Only launch when step is pending. This guard breaks the re-trigger loop:
    # Lambda writes manifest (status=running) -> S3 event fires -> Lambda reads
    # manifest, sees "running", returns here.
    if step_status != "pending":
        print(f"Step {step_idx} is '{step_status}', not 'pending'. No action.")
        return {"status": "no-op", "step_status": step_status}

    # Mark step as running
    step["status"] = "running"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(manifest, indent=2, default=str).encode("utf-8"),
    )

    # Launch ECS Fargate task
    plugin_name = step["agent"]
    print(f"Launching step {step_idx}: agent={plugin_name}, prefix={run_prefix}")

    response = ecs.run_task(
        cluster=CLUSTER_ARN,
        taskDefinition=TASK_DEF_ARN,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": SUBNET_IDS,
                "securityGroups": SG_IDS,
                "assignPublicIp": "ENABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": CONTAINER_NAME,
                    "environment": [
                        {"name": "PLUGIN_NAME", "value": plugin_name},
                        {"name": "RUN_PREFIX", "value": run_prefix},
                        {"name": "AGENT_RUNTIME", "value": AGENT_RUNTIME},
                        {"name": "LLM_MODEL", "value": LLM_MODEL},
                    ],
                }
            ]
        },
    )

    failures = response.get("failures", [])
    if failures:
        print(f"RunTask failures: {json.dumps(failures)}")
        step["status"] = "failed"
        step["error"] = f"RunTask failed: {json.dumps(failures)}"
        manifest["status"] = "failed"
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(manifest, indent=2, default=str).encode("utf-8"),
        )
        return {"status": "failed", "failures": failures}

    task_arn = response["tasks"][0]["taskArn"]
    print(f"Launched task {task_arn} for step {step_idx} ({plugin_name})")

    return {
        "status": "launched",
        "task_arn": task_arn,
        "step": step_idx,
        "agent": plugin_name,
    }
