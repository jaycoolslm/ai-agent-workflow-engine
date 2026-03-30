"""
Storage protocol: the contract every backend must satisfy.

All methods use string keys (S3-style paths like "runs/run_001/manifest.json").
Implementations handle mapping these to their native concepts
(S3 keys, Blob paths, GCS object names).
"""

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProtocol(Protocol):
    """Interface for object storage backends."""

    def read_json(self, key: str) -> dict:
        """Read a JSON object and return it as a dict."""
        ...

    def write_json(self, key: str, data: dict) -> None:
        """Serialize a dict as JSON and write it."""
        ...

    def read_bytes(self, key: str) -> bytes:
        """Read raw bytes from a key."""
        ...

    def write_bytes(self, key: str, data: bytes) -> None:
        """Write raw bytes to a key."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """List all keys under a prefix."""
        ...

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        """Copy all objects under src_prefix to dst_prefix."""
        ...

    def key_exists(self, key: str) -> bool:
        """Check whether a key exists."""
        ...

    def download_prefix_to_dir(self, prefix: str, local_dir: Path) -> None:
        """Download all objects under a prefix into a local directory."""
        ...

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str) -> None:
        """Upload all files in a local directory to a prefix."""
        ...
