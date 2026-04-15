"""
Storage Provider Abstraction Layer for S3 Files (Direct NFS Mount).

Provides a simplified file-oriented API (upload_file, download_file, list_files)
on top of the existing StorageProtocol infrastructure. Two concrete
implementations:

  - Boto3Storage: Uses the existing boto3 S3 API (MinIO, AWS S3).
    Incurs full HTTP round-trip latency per operation.

  - DirectMountStorage: Uses standard Python os/shutil on a locally-mounted
    filesystem.  This simulates Amazon S3 Files (Direct NFS Mount), where
    the S3 bucket is presented as a POSIX path with zero-copy handover.

Usage:
    from storage_provider import get_storage_provider

    provider = get_storage_provider()          # reads STORAGE_MODE env
    provider.upload_file(local_path, "runs/run_001/step_0/output/report.md")
    provider.download_file("runs/run_001/step_0/output/report.md", local_path)
    files = provider.list_files("runs/run_001/step_0/output/")

Environment:
    STORAGE_MODE   – 's3' (default) or 'direct_mount'
    S3_ENDPOINT    – MinIO / S3 endpoint (for s3 mode)
    NFS_MOUNT_PATH – local mount path   (for direct_mount mode)
    BUCKET         – bucket name
"""

from __future__ import annotations

import json
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config


# ---------------------------------------------------------------------------
# Abstract Base Class
# ---------------------------------------------------------------------------

class StorageProvider(ABC):
    """
    Abstract storage provider for the workflow engine.

    Every implementation must support three file-level operations:
      upload_file   – push a local file to the store
      download_file – pull a remote key to a local path
      list_files    – enumerate keys under a prefix
    """

    @abstractmethod
    def upload_file(self, local_path: str | Path, remote_key: str) -> None:
        """Upload a local file to the given remote key."""
        ...

    @abstractmethod
    def download_file(self, remote_key: str, local_path: str | Path) -> None:
        """Download a remote key to a local file path."""
        ...

    @abstractmethod
    def list_files(self, prefix: str) -> list[str]:
        """List all keys under *prefix*."""
        ...

    # ----- convenience helpers (non-abstract) ----
    def upload_dir(self, local_dir: str | Path, prefix: str) -> list[str]:
        """Upload every file under *local_dir* to ``prefix/…``."""
        uploaded: list[str] = []
        local_dir = Path(local_dir)
        for fpath in local_dir.rglob("*"):
            if fpath.is_file():
                rel = fpath.relative_to(local_dir)
                key = f"{prefix}/{rel}".replace("\\", "/")
                self.upload_file(fpath, key)
                uploaded.append(key)
        return uploaded

    def download_prefix(self, prefix: str, local_dir: str | Path) -> list[str]:
        """Download all keys under *prefix* into *local_dir*."""
        downloaded: list[str] = []
        local_dir = Path(local_dir)
        for key in self.list_files(prefix):
            rel = key[len(prefix):].lstrip("/")
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.download_file(key, dest)
            downloaded.append(str(dest))
        return downloaded

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> int:
        """Copy all keys from *src_prefix* to *dst_prefix*. Returns count."""
        keys = self.list_files(src_prefix)
        for key in keys:
            suffix = key[len(src_prefix):]
            new_key = dst_prefix + suffix
            self._copy_key(key, new_key)
        return len(keys)

    def _copy_key(self, src_key: str, dst_key: str) -> None:
        """Default copy via download-then-upload (overridden for efficiency)."""
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            self.download_file(src_key, tmp_path)
            self.upload_file(tmp_path, dst_key)
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Boto3Storage – wraps existing S3 / MinIO code path
# ---------------------------------------------------------------------------

class Boto3Storage(StorageProvider):
    """
    S3-compatible storage via boto3.

    Every operation crosses the network (even when MinIO runs locally),
    incurring serialize → HTTP PUT/GET → deserialize latency.
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str = "",
        region: str = "us-east-1",
    ):
        kwargs: dict = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
            kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )
        else:
            kwargs["config"] = Config(signature_version="s3v4")

        self.s3 = boto3.client("s3", **kwargs)
        self.bucket = bucket

    # --- core API ---
    def upload_file(self, local_path: str | Path, remote_key: str) -> None:
        self.s3.upload_file(str(local_path), self.bucket, remote_key)

    def download_file(self, remote_key: str, local_path: str | Path) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, remote_key, str(local_path))

    def list_files(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    # --- optimised copy (server-side) ---
    def _copy_key(self, src_key: str, dst_key: str) -> None:
        self.s3.copy_object(
            Bucket=self.bucket,
            CopySource={"Bucket": self.bucket, "Key": src_key},
            Key=dst_key,
        )


# ---------------------------------------------------------------------------
# DirectMountStorage – local filesystem (simulates Amazon S3 Files NFS mount)
# ---------------------------------------------------------------------------

class DirectMountStorage(StorageProvider):
    """
    "Direct mount" storage using standard ``os`` / ``shutil``.

    In production this targets an Amazon S3 Files NFS mount path where
    the S3 bucket is exposed directly as a POSIX filesystem.  Locally it
    simply uses a temp directory, giving identical semantics at zero
    network latency.
    """

    def __init__(
        self,
        bucket: str,
        mount_path: str = "",
    ):
        self.mount_path = Path(
            mount_path or os.environ.get("NFS_MOUNT_PATH", "")
        )
        # Fall back to a temp dir so local tests always work.
        if not self.mount_path or not self.mount_path.exists():
            import tempfile
            self.mount_path = Path(tempfile.mkdtemp(prefix="direct_mount_"))

        self.root = self.mount_path / bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        resolved = (self.root / key).resolve()
        root_resolved = self.root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise ValueError(f"Path traversal detected: {key}")
        return resolved

    # --- core API ---
    def upload_file(self, local_path: str | Path, remote_key: str) -> None:
        dst = self._resolve(remote_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(local_path), str(dst))

    def download_file(self, remote_key: str, local_path: str | Path) -> None:
        src = self._resolve(remote_key)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(local_path))

    def list_files(self, prefix: str) -> list[str]:
        prefix_path = self._resolve(prefix)
        if not prefix_path.exists():
            return []
        keys: list[str] = []
        if prefix_path.is_file():
            keys.append(prefix)
        else:
            for p in prefix_path.rglob("*"):
                if p.is_file():
                    keys.append(str(p.relative_to(self.root)).replace("\\", "/"))
        return keys

    # --- optimised copy (local fs, no network) ---
    def _copy_key(self, src_key: str, dst_key: str) -> None:
        src = self._resolve(src_key)
        dst = self._resolve(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> int:
        """Optimised: single shutil.copytree when both sides are directories."""
        src_path = self._resolve(src_prefix)
        if not src_path.exists():
            return 0
        dst_path = self._resolve(dst_prefix)
        dst_path.mkdir(parents=True, exist_ok=True)
        count = 0
        for fpath in src_path.rglob("*"):
            if fpath.is_file():
                rel = fpath.relative_to(src_path)
                dest = dst_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(fpath), str(dest))
                count += 1
        return count


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_storage_provider(
    mode: str | None = None,
    bucket: str | None = None,
    **kwargs,
) -> StorageProvider:
    """
    Create a StorageProvider from env vars or explicit arguments.

    Args:
        mode:   's3' | 'direct_mount'. Defaults to env STORAGE_MODE or 's3'.
        bucket: Bucket name. Defaults to env BUCKET.
        **kwargs: Forwarded to the chosen backend constructor.
    """
    mode = mode or os.environ.get("STORAGE_MODE", "s3")
    bucket = bucket or os.environ.get("BUCKET", "workflows")

    if mode == "s3":
        endpoint_url = kwargs.pop("endpoint_url", os.environ.get("S3_ENDPOINT", ""))
        region = kwargs.pop("region", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        return Boto3Storage(bucket=bucket, endpoint_url=endpoint_url, region=region)

    if mode == "direct_mount":
        mount_path = kwargs.pop("mount_path", os.environ.get("NFS_MOUNT_PATH", ""))
        return DirectMountStorage(bucket=bucket, mount_path=mount_path)

    raise ValueError(
        f"Unknown STORAGE_MODE: '{mode}'. Use 's3' or 'direct_mount'."
    )
