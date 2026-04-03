"""
Azure Function router: Event Grid blob event -> read manifest -> launch ACI container.

Triggered by Event Grid when a blob ending in manifest.json is created/updated.
Stateless - when the container finishes and writes the updated manifest back,
this function is re-triggered and either launches the next step or no-ops.
"""

import json
import logging
import os

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.mgmt.containerinstance import ContainerInstanceManagementClient
from azure.mgmt.containerinstance.models import (
    Container,
    ContainerGroup,
    ContainerGroupDiagnostics,
    ContainerGroupIdentity,
    ContainerGroupRestartPolicy,
    EnvironmentVariable,
    ImageRegistryCredential,
    LogAnalytics,
    OperatingSystemTypes,
    ResourceIdentityType,
    ResourceRequests,
    ResourceRequirements,
)
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp()

# Configuration from Function App settings (set by Terraform)
STORAGE_ACCOUNT_NAME = os.environ.get("STORAGE_ACCOUNT_NAME", "")
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "workflows")
ACR_LOGIN_SERVER = os.environ.get("ACR_LOGIN_SERVER", "")
AGENT_IMAGE_TAG = os.environ.get("AGENT_IMAGE_TAG", "latest")
RESOURCE_GROUP_NAME = os.environ.get("RESOURCE_GROUP_NAME", "")
AZURE_REGION = os.environ.get("AZURE_REGION", "eastus")
KEYVAULT_URI = os.environ.get("KEYVAULT_URI", "")
CONTAINER_CPU = float(os.environ.get("CONTAINER_CPU", "1.0"))
CONTAINER_MEMORY_GB = float(os.environ.get("CONTAINER_MEMORY_GB", "4.0"))
MANAGED_IDENTITY_ID = os.environ.get("MANAGED_IDENTITY_ID", "")
FUNCTION_IDENTITY_CLIENT_ID = os.environ.get("FUNCTION_IDENTITY_CLIENT_ID", "")
MANAGED_IDENTITY_CLIENT_ID = os.environ.get("MANAGED_IDENTITY_CLIENT_ID", "")
SUBSCRIPTION_ID = os.environ.get("SUBSCRIPTION_ID", "")
LOG_ANALYTICS_WORKSPACE_ID = os.environ.get("LOG_ANALYTICS_WORKSPACE_ID", "")
LOG_ANALYTICS_WORKSPACE_KEY = os.environ.get("LOG_ANALYTICS_WORKSPACE_KEY", "")
AGENT_RUNTIME = os.environ.get("AGENT_RUNTIME", "claude")
LLM_MODEL = os.environ.get("LLM_MODEL", "")

credential = DefaultAzureCredential(
    managed_identity_client_id=FUNCTION_IDENTITY_CLIENT_ID
)


def _get_blob_service() -> BlobServiceClient:
    return BlobServiceClient(
        account_url=f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net",
        credential=credential,
    )


def _get_api_key() -> str:
    """Retrieve the Anthropic API key from Key Vault."""
    client = SecretClient(vault_url=KEYVAULT_URI, credential=credential)
    return client.get_secret("anthropic-api-key").value


def _read_manifest(blob_service: BlobServiceClient, run_prefix: str) -> dict:
    container = blob_service.get_container_client(CONTAINER_NAME)
    blob = container.get_blob_client(f"{run_prefix}/manifest.json")
    data = blob.download_blob().readall()
    return json.loads(data)


def _write_manifest(blob_service: BlobServiceClient, run_prefix: str, manifest: dict):
    container = blob_service.get_container_client(CONTAINER_NAME)
    blob = container.get_blob_client(f"{run_prefix}/manifest.json")
    body = json.dumps(manifest, indent=2, default=str).encode("utf-8")
    blob.upload_blob(body, overwrite=True)


@app.function_name("router")
@app.event_grid_trigger(arg_name="event")
def router(event: func.EventGridEvent):
    """Handle Event Grid blob-created events for manifest.json files."""
    subject = event.subject
    logging.info(f"Event Grid trigger: subject={subject}")

    # Subject format: /blobServices/default/containers/{container}/blobs/{blob_path}
    # Extract the blob path after /blobs/
    if "/blobs/" not in subject:
        logging.info(f"Ignoring event with unexpected subject: {subject}")
        return

    blob_path = subject.split("/blobs/", 1)[1]

    if not blob_path.endswith("/manifest.json"):
        logging.info(f"Ignoring non-manifest blob: {blob_path}")
        return

    # Derive run_prefix: "runs/run_001/manifest.json" -> "runs/run_001"
    run_prefix = blob_path.rsplit("/manifest.json", 1)[0]
    logging.info(f"Processing manifest for run: {run_prefix}")

    blob_service = _get_blob_service()

    # Read manifest
    manifest = _read_manifest(blob_service, run_prefix)

    # Terminal states - nothing to do
    workflow_status = manifest.get("status", "")
    if workflow_status in ("complete", "failed"):
        logging.info(f"Workflow {workflow_status}. No action.")
        return

    step_idx = manifest["current_step"]
    step = manifest["steps"][step_idx]
    step_status = step["status"]

    # Only launch when step is pending. This guard breaks the re-trigger loop:
    # Function writes manifest (status=running) -> Event Grid fires -> Function
    # reads manifest, sees "running", returns here.
    if step_status != "pending":
        logging.info(f"Step {step_idx} is '{step_status}', not 'pending'. No action.")

        # Clean up completed/failed container groups to avoid clutter
        if step_status in ("complete", "failed"):
            group_name = f"{run_prefix.replace('/', '-')}-step-{step_idx}"
            try:
                aci_client = ContainerInstanceManagementClient(credential, SUBSCRIPTION_ID)
                aci_client.container_groups.begin_delete(RESOURCE_GROUP_NAME, group_name)
                logging.info(f"Deleted container group '{group_name}'")
            except Exception as e:
                logging.warning(f"Failed to delete container group '{group_name}': {e}")

        return

    # Mark step as running
    step["status"] = "running"
    _write_manifest(blob_service, run_prefix, manifest)

    # Launch ACI container
    plugin_name = step["agent"]
    logging.info(f"Launching step {step_idx}: agent={plugin_name}, prefix={run_prefix}")

    try:
        api_key = _get_api_key()

        aci_client = ContainerInstanceManagementClient(credential, SUBSCRIPTION_ID)

        # Unique name for this container group (Azure resource name)
        group_name = f"{run_prefix.replace('/', '-')}-step-{step_idx}"

        container_group = ContainerGroup(
            location=AZURE_REGION,
            identity=ContainerGroupIdentity(
                type=ResourceIdentityType.USER_ASSIGNED,
                user_assigned_identities={MANAGED_IDENTITY_ID: {}},
            ),
            os_type=OperatingSystemTypes.LINUX,
            restart_policy=ContainerGroupRestartPolicy.NEVER,
            image_registry_credentials=[
                ImageRegistryCredential(
                    server=ACR_LOGIN_SERVER,
                    identity=MANAGED_IDENTITY_ID,
                )
            ],
            containers=[
                Container(
                    name="agent",
                    image=f"{ACR_LOGIN_SERVER}/agent-workflow-engine/agent:{AGENT_IMAGE_TAG}",
                    resources=ResourceRequirements(
                        requests=ResourceRequests(
                            cpu=CONTAINER_CPU,
                            memory_in_gb=CONTAINER_MEMORY_GB,
                        )
                    ),
                    environment_variables=[
                        EnvironmentVariable(name="STORAGE_BACKEND", value="azure"),
                        EnvironmentVariable(name="BUCKET", value=CONTAINER_NAME),
                        EnvironmentVariable(name="RUN_PREFIX", value=run_prefix),
                        EnvironmentVariable(name="PLUGIN_NAME", value=plugin_name),
                        EnvironmentVariable(name="AZURE_STORAGE_ACCOUNT", value=STORAGE_ACCOUNT_NAME),
                        EnvironmentVariable(name="AZURE_CLIENT_ID", value=MANAGED_IDENTITY_CLIENT_ID),
                        EnvironmentVariable(name="AGENT_RUNTIME", value=AGENT_RUNTIME),
                        EnvironmentVariable(name="LLM_MODEL", value=LLM_MODEL),
                        EnvironmentVariable(name="ANTHROPIC_API_KEY", secure_value=api_key),
                    ],
                )
            ],
            diagnostics=ContainerGroupDiagnostics(
                log_analytics=LogAnalytics(
                    workspace_id=LOG_ANALYTICS_WORKSPACE_ID,
                    workspace_key=LOG_ANALYTICS_WORKSPACE_KEY,
                )
            ) if LOG_ANALYTICS_WORKSPACE_ID else None,
        )

        poller = aci_client.container_groups.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            group_name,
            container_group,
        )
        logging.info(f"ACI container group '{group_name}' creation started")

    except Exception as e:
        logging.error(f"Failed to launch ACI container: {e}")
        step["status"] = "failed"
        step["error"] = f"ACI launch failed: {str(e)}"
        manifest["status"] = "failed"
        _write_manifest(blob_service, run_prefix, manifest)
        return

    logging.info(f"Launched container for step {step_idx} ({plugin_name})")
