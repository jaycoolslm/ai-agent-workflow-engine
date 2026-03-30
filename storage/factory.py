"""
Storage factory: creates the right backend from a backend name + config.
"""

from storage.protocol import StorageProtocol


def get_storage(backend: str, **kwargs) -> StorageProtocol:
    """
    Create a storage backend instance.

    Args:
        backend: One of "s3", "gcs", "azure".
        **kwargs: Backend-specific config passed to the constructor.
            s3:    bucket, endpoint_url, region
            gcs:   bucket, project
            azure: container, connection_string
    """
    if backend == "s3":
        from storage.s3 import S3Storage
        return S3Storage(**kwargs)

    if backend == "gcs":
        from storage.gcs import GCSStorage
        return GCSStorage(**kwargs)

    if backend == "azure":
        from storage.azure import AzureBlobStorage
        return AzureBlobStorage(**kwargs)

    raise ValueError(f"Unknown storage backend: '{backend}'. Use 's3', 'gcs', or 'azure'.")
