"""
S3 storage backend. Works with AWS S3, MinIO, and any S3-compatible store.
"""

import json
from pathlib import Path

import boto3
from botocore.config import Config


class S3Storage:
    """S3-compatible storage backend (AWS S3, MinIO, etc.)."""

    def __init__(self, bucket: str, endpoint_url: str = "", region: str = "us-east-1"):
        kwargs: dict = {
            "region_name": region,
            "config": Config(signature_version="s3v4"),
        }
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
            kwargs["config"] = Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            )

        self.s3 = boto3.client("s3", **kwargs)
        self.bucket = bucket

    def read_json(self, key: str) -> dict:
        resp = self.s3.get_object(Bucket=self.bucket, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))

    def write_json(self, key: str, data: dict) -> None:
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body)

    def read_bytes(self, key: str) -> bytes:
        resp = self.s3.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def write_bytes(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def copy_prefix(self, src_prefix: str, dst_prefix: str) -> None:
        for key in self.list_keys(src_prefix):
            new_key = dst_prefix + key[len(src_prefix):]
            self.s3.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": key},
                Key=new_key,
            )

    def key_exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.s3.exceptions.ClientError:
            return False

    def download_prefix_to_dir(self, prefix: str, local_dir: Path) -> None:
        for key in self.list_keys(prefix):
            rel = key[len(prefix):].lstrip("/")
            if not rel:
                continue
            local_path = local_dir / rel
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.s3.download_file(self.bucket, key, str(local_path))

    def upload_dir_to_prefix(self, local_dir: Path, prefix: str) -> None:
        for local_path in local_dir.rglob("*"):
            if local_path.is_file():
                rel = local_path.relative_to(local_dir)
                key = f"{prefix}/{rel}"
                self.s3.upload_file(str(local_path), self.bucket, key)
