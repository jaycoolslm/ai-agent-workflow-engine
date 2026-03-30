"""
GCP Cloud Function router: GCS event -> read manifest -> launch Cloud Run Job.

Triggered by GCS finalize (object creation) on **/manifest.json. Stateless — no polling loop.
When the container finishes and writes the updated manifest back to GCS,
this Cloud Function is re-triggered and either launches the next step or no-ops.
"""

import json
import os

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import run_v2, storage

gcs = storage.Client()
jobs_client = run_v2.JobsClient()

GCP_PROJECT = os.environ["GCP_PROJECT"]
GCP_REGION = os.environ["GCP_REGION"]
CLOUD_RUN_JOB_NAME = os.environ["CLOUD_RUN_JOB_NAME"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
AGENT_RUNTIME = os.environ.get("AGENT_RUNTIME", "claude")
LLM_MODEL = os.environ.get("LLM_MODEL", "")


@functions_framework.cloud_event
def handler(cloud_event: CloudEvent):
    data = cloud_event.data
    bucket = data["bucket"]
    key = data["name"]

    # Only act on manifest.json files
    if not key.endswith("/manifest.json"):
        print(f"Ignoring non-manifest key: {key}")
        return {"status": "ignored"}

    # Derive run_prefix: "runs/run_001/manifest.json" -> "runs/run_001"
    run_prefix = key.rsplit("/manifest.json", 1)[0]

    # Read manifest
    blob = gcs.bucket(bucket).blob(key)
    manifest = json.loads(blob.download_as_text())

    # Terminal states — nothing to do
    workflow_status = manifest.get("status", "")
    if workflow_status in ("complete", "failed"):
        print(f"Workflow {workflow_status}. No action.")
        return {"status": workflow_status}

    step_idx = manifest["current_step"]
    step = manifest["steps"][step_idx]
    step_status = step["status"]

    # Only launch when step is pending. This guard breaks the re-trigger loop:
    # Cloud Function writes manifest (status=running) -> GCS event fires ->
    # Cloud Function reads manifest, sees "running", returns here.
    if step_status != "pending":
        print(f"Step {step_idx} is '{step_status}', not 'pending'. No action.")
        return {"status": "no-op", "step_status": step_status}

    # Mark step as running
    step["status"] = "running"
    blob.upload_from_string(
        json.dumps(manifest, indent=2, default=str),
        content_type="application/json",
    )

    # Launch Cloud Run Job
    plugin_name = step["agent"]
    print(f"Launching step {step_idx}: agent={plugin_name}, prefix={run_prefix}")

    job_full_name = (
        f"projects/{GCP_PROJECT}/locations/{GCP_REGION}/jobs/{CLOUD_RUN_JOB_NAME}"
    )

    request = run_v2.RunJobRequest(
        name=job_full_name,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=[
                        run_v2.EnvVar(name="PLUGIN_NAME", value=plugin_name),
                        run_v2.EnvVar(name="RUN_PREFIX", value=run_prefix),
                        run_v2.EnvVar(name="AGENT_RUNTIME", value=AGENT_RUNTIME),
                        run_v2.EnvVar(name="LLM_MODEL", value=LLM_MODEL),
                    ]
                )
            ]
        ),
    )

    try:
        operation = jobs_client.run_job(request=request)
    except Exception as e:
        error_msg = str(e)
        print(f"RunJob failure: {error_msg}")
        step["status"] = "failed"
        step["error"] = f"RunJob failed: {error_msg}"
        manifest["status"] = "failed"
        blob.upload_from_string(
            json.dumps(manifest, indent=2, default=str),
            content_type="application/json",
        )
        return {"status": "failed", "error": error_msg}

    execution_name = operation.metadata.name if operation.metadata else "unknown"
    print(f"Launched job execution {execution_name} for step {step_idx} ({plugin_name})")

    return {
        "status": "launched",
        "execution": execution_name,
        "step": step_idx,
        "agent": plugin_name,
    }
