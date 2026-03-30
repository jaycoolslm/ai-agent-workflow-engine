"""
Cloud-agnostic storage abstraction.

Usage:
    from storage import get_storage

    storage = get_storage(backend="s3", bucket="my-bucket", endpoint_url="http://localhost:9000")
    storage.write_json("path/to/key.json", {"hello": "world"})
"""

from storage.protocol import StorageProtocol
from storage.factory import get_storage

__all__ = ["StorageProtocol", "get_storage"]
