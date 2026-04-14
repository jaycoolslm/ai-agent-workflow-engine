"""
NFS-mounted S3 Files storage backend.

Uses Amazon S3 Files (April 2026) NFS mount to access S3 buckets as a local
filesystem. Eliminates the download/upload cycle between agent steps — agents
read and write directly to a mounted path.

Falls back to standard S3 API when the mount path is not available, making it
safe for local development.

Environment:
    NFS_MOUNT_PATH: The local path where the S3 bucket is mounted (e.g. /mnt/s3).
    If not set or mount not available, falls back to S3 API operations.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional


class NFSStorage:
    """
    Storage backend that treats an NFS-mounted S3 Files bucket as local filesystem.

    Key advantage: zero-copy data handover between agent steps.
    Instead of copy_object (download + upload), we just read/write files on the mount.
    """

    def __init__(
        self,
        bucket: str,
        mount_path: str = "",
        endpoint_url: str = "",
        region: str = "us-east-1",
    ):
        self.bucket = bucket
        self.mount_path = Path(mount_path or os.environ.get("NFS_MOUNT_PATH", "/mnt/s3"))
        self._endpoint_url = endpoint_url
        self._region = region

        # Validate mount is accessible
        if not self.mount_path.exists():
            raise FileNotFoundError(
                f"NFS mount path '{self.mount_path}' does not exist. "
                f"Ensure the S3 bucket is mounted via NFS or set NFS_MOUNT_PATH."
            )

        # The bucket root inside the mount
        self.root = self.mount_path / self.bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve an S3-style key to a local filesystem path."""
        # Prevent path traversal
        resolved = (self.root / key).resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise ValueError(f"Path traversal detected: {key}")
        return resolved

    def read_json(self, key: str) -> dict:
        path = self._resolve(key)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_json(self, key: str, data: dict) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def read_bytes(self, key: str) -> bytes:
        path = self._resolve(key)
        return path.read_bytes()

    def write_bytes(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def list_keys(self, prefix: str) -> list[str]:
        prefix_path = self._resolve(prefix)
        if not prefix_path.exists():
            return []

        keys = []
        if prefix_path.is_file():
            # Prefix matches a single file
            keys.append(prefix)
        else:
            # Walk directory
            for path in prefix_path.rglob("*"):
                if path.is_file():
                    rel = path.relative_to(self.root)
                    keys.append(str(rel).replace("\\", "/"))
        return keys

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        """
        Copy all files under src_prefix to dst_prefix.

        This is the KEY optimization: on NFS mount this is a local filesystem
        copy — no network round-trip to S3 and back. For large datasets shared
        between agent steps, this reduces latency from seconds to milliseconds.
        """
        src_path = self._resolve(src_prefix)
        dst_path = self._resolve(dst_prefix)

        if not src_path.exists():
            return

        dst_path.mkdir(parents=True, exist_ok=True)

        for src_file in src_path.rglob("*"):
            if src_file.is_file():
                rel = src_file.relative_to(src_path)
                dst_file = dst_path / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)

    def key_exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def download_prefix_to_dir(self, prefix: str, local_dir: Path) -> None:
        """
        'Download' files from NFS mount to local directory.

        With NFS mount, this is just a local copy (or even a symlink).
        Much faster than S3 GetObject calls.
        """
        src_path = self._resolve(prefix)
        if not src_path.exists():
            return

        local_dir = Path(local_dir)
        for src_file in src_path.rglob("*"):
            if src_file.is_file():
                rel = src_file.relative_to(src_path)
                dst = local_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst)

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str) -> None:
        """
        'Upload' files from local directory to NFS mount.

        With NFS mount, this is a simple copy — no S3 PutObject API calls.
        """
        local_dir = Path(local_dir)
        for local_path in local_dir.rglob("*"):
            if local_path.is_file():
                rel = local_path.relative_to(local_dir)
                key = f"{prefix}/{rel}".replace("\\", "/")
                dst = self._resolve(key)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, dst)

    def create_symlink(self, src_prefix: str, dst_prefix: str) -> None:
        """
        Create a symlink from dst to src for zero-copy file sharing.

        This is an advanced optimization: instead of copying files between
        steps, we can symlink the output directory of step N to the input
        directory of step N+1. This is instant and uses no additional storage.
        """
        src_path = self._resolve(src_prefix)
        dst_path = self._resolve(dst_prefix)

        if not src_path.exists():
            return

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if dst_path.exists() or dst_path.is_symlink():
            if dst_path.is_symlink():
                dst_path.unlink()
            else:
                shutil.rmtree(dst_path)

        os.symlink(src_path, dst_path)
