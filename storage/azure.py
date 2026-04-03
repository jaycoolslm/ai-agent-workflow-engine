"""
Azure Blob Storage backend.

Requires: pip install azure-storage-blob azure-identity
"""

import json
import os
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient


class AzureBlobStorage:
    """Azure Blob Storage backend (Azure, Azurite)."""

    def __init__(self, container: str, connection_string: str = ""):
        if connection_string:
            self._service = BlobServiceClient.from_connection_string(connection_string)
        else:
            # Production: use DefaultAzureCredential with storage account name
            account_name = os.environ.get("AZURE_STORAGE_ACCOUNT", "")
            if not account_name:
                raise ValueError(
                    "AzureBlobStorage requires either connection_string or "
                    "AZURE_STORAGE_ACCOUNT env var for managed identity auth."
                )
            from azure.identity import DefaultAzureCredential

            managed_identity_client_id = os.environ.get("AZURE_CLIENT_ID", "")
            credential = DefaultAzureCredential(
                managed_identity_client_id=managed_identity_client_id or None,
            )
            self._service = BlobServiceClient(
                account_url=f"https://{account_name}.blob.core.windows.net",
                credential=credential,
            )

        self._container_name = container
        self._container = self._service.get_container_client(container)

    def read_json(self, key: str) -> dict:
        blob = self._container.get_blob_client(key)
        data = blob.download_blob().readall()
        return json.loads(data)

    def write_json(self, key: str, data: dict) -> None:
        blob = self._container.get_blob_client(key)
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        blob.upload_blob(body, overwrite=True)

    def read_bytes(self, key: str) -> bytes:
        blob = self._container.get_blob_client(key)
        return blob.download_blob().readall()

    def write_bytes(self, key: str, data: bytes) -> None:
        blob = self._container.get_blob_client(key)
        blob.upload_blob(data, overwrite=True)

    def list_keys(self, prefix: str) -> list[str]:
        return [b.name for b in self._container.list_blobs(name_starts_with=prefix)]

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        for blob_props in self._container.list_blobs(name_starts_with=src_prefix):
            src_blob = self._container.get_blob_client(blob_props.name)
            relative = blob_props.name[len(src_prefix):]
            dst_key = dst_prefix + relative
            dst_blob = self._container.get_blob_client(dst_key)
            # Same-account copy uses the source blob URL directly.
            # Cross-account would require a SAS token on the source URL.
            dst_blob.start_copy_from_url(src_blob.url)

    def key_exists(self, key: str) -> bool:
        blob = self._container.get_blob_client(key)
        try:
            blob.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False

    def download_prefix_to_dir(self, prefix: str, local_dir: Path) -> None:
        for blob_props in self._container.list_blobs(name_starts_with=prefix):
            rel = blob_props.name[len(prefix):].lstrip("/")
            if not rel:
                continue
            local_path = local_dir / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob = self._container.get_blob_client(blob_props.name)
            with open(local_path, "wb") as f:
                blob.download_blob().readinto(f)

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str) -> None:
        for local_path in local_dir.rglob("*"):
            if local_path.is_file():
                rel = local_path.relative_to(local_dir)
                key = f"{prefix}/{rel}"
                blob = self._container.get_blob_client(key)
                with open(local_path, "rb") as f:
                    blob.upload_blob(f, overwrite=True)
