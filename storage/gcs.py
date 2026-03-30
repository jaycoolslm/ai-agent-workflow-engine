"""
Google Cloud Storage backend. Works with GCS and fake-gcs-server (local emulator).

Requires: pip install google-cloud-storage
"""

import json
import os
from pathlib import Path

from google.cloud import storage


class GCSStorage:
    """Google Cloud Storage backend."""

    def __init__(self, bucket: str, project: str = ""):
        kwargs: dict = {}
        if project:
            kwargs["project"] = project

        # When STORAGE_EMULATOR_HOST is set (fake-gcs-server), use anonymous creds.
        # The SDK auto-routes requests to the emulator endpoint.
        if os.environ.get("STORAGE_EMULATOR_HOST"):
            from google.auth.credentials import AnonymousCredentials

            kwargs["credentials"] = AnonymousCredentials()
            if not project:
                kwargs["project"] = "test"

        self.client = storage.Client(**kwargs)
        self.bucket = self.client.bucket(bucket)

    def read_json(self, key: str) -> dict:
        blob = self.bucket.blob(key)
        data = blob.download_as_text(encoding="utf-8")
        return json.loads(data)

    def write_json(self, key: str, data: dict) -> None:
        blob = self.bucket.blob(key)
        body = json.dumps(data, indent=2, default=str)
        blob.upload_from_string(body, content_type="application/json")

    def read_bytes(self, key: str) -> bytes:
        blob = self.bucket.blob(key)
        return blob.download_as_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        blob = self.bucket.blob(key)
        blob.upload_from_string(data, content_type="application/octet-stream")

    def list_keys(self, prefix: str) -> list[str]:
        blobs = self.client.list_blobs(self.bucket, prefix=prefix)
        return [blob.name for blob in blobs]

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        for blob in self.client.list_blobs(self.bucket, prefix=src_prefix):
            new_name = dst_prefix + blob.name[len(src_prefix):]
            self.bucket.copy_blob(blob, self.bucket, new_name)

    def key_exists(self, key: str) -> bool:
        blob = self.bucket.blob(key)
        return blob.exists()

    def download_prefix_to_dir(self, prefix: str, local_dir: Path) -> None:
        for blob in self.client.list_blobs(self.bucket, prefix=prefix):
            rel = blob.name[len(prefix):].lstrip("/")
            if not rel:
                continue
            local_path = local_dir / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(local_path))

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str) -> None:
        for local_path in local_dir.rglob("*"):
            if local_path.is_file():
                rel = local_path.relative_to(local_dir)
                key = f"{prefix}/{rel}"
                blob = self.bucket.blob(key)
                blob.upload_from_filename(str(local_path))
