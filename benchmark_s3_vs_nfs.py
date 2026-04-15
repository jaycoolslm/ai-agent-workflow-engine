"""
Benchmark: Boto3Storage (S3 HTTP API) vs DirectMountStorage (NFS Direct Mount).

Compares the full step-handover lifecycle — upload, download, copy_prefix —
at multiple file sizes.  Requires MinIO running for the S3 path; the NFS
path uses a local temp directory (identical semantics to an NFS mount).

Usage:
    # Start MinIO first
    docker compose up minio -d

    # Run the benchmark
    python benchmark_s3_vs_nfs.py

    # Run with custom sizes (in MB)
    python benchmark_s3_vs_nfs.py --sizes 1 5 25 50 100
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from storage_provider import Boto3Storage, DirectMountStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_test_file(path: Path, size_mb: int) -> None:
    """Create a file of the given size filled with deterministic bytes."""
    chunk = b"A" * (1024 * 1024)  # 1 MB chunk
    with open(path, "wb") as f:
        for _ in range(size_mb):
            f.write(chunk)


def ensure_minio_bucket(endpoint: str, bucket: str) -> bool:
    """Create the benchmark bucket in MinIO if it doesn't exist. Returns True if reachable."""
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        try:
            s3.head_bucket(Bucket=bucket)
        except ClientError:
            s3.create_bucket(Bucket=bucket)
        return True
    except Exception as e:
        print(f"  [WARN] Cannot reach MinIO at {endpoint}: {e}")
        return False


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:>8.1f} ms"


def fmt_mbps(size_mb: int, seconds: float) -> str:
    if seconds <= 0:
        return "     inf MB/s"
    return f"{size_mb / seconds:>8.1f} MB/s"


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def benchmark_provider(
    label: str,
    provider,
    local_file: Path,
    size_mb: int,
    prefix: str,
    iterations: int = 3,
) -> dict:
    """Run upload → download → copy_prefix for the given provider, return timings."""
    remote_key = f"{prefix}/step_0/output/payload.bin"
    copy_src = f"{prefix}/step_0/output/"
    copy_dst = f"{prefix}/step_1/input/"

    upload_times = []
    download_times = []
    copy_times = []

    for i in range(iterations):
        # Upload
        t0 = time.perf_counter()
        provider.upload_file(local_file, remote_key)
        upload_times.append(time.perf_counter() - t0)

        # Download
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            dl_path = Path(tmp.name)
        try:
            t0 = time.perf_counter()
            provider.download_file(remote_key, dl_path)
            download_times.append(time.perf_counter() - t0)
        finally:
            dl_path.unlink(missing_ok=True)

        # Copy prefix (step handover: step_0/output → step_1/input)
        t0 = time.perf_counter()
        provider.copy_prefix(copy_src, copy_dst)
        copy_times.append(time.perf_counter() - t0)

    return {
        "label": label,
        "size_mb": size_mb,
        "upload_median": statistics.median(upload_times),
        "download_median": statistics.median(download_times),
        "copy_median": statistics.median(copy_times),
        "upload_all": upload_times,
        "download_all": download_times,
        "copy_all": copy_times,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_results(s3_results: list[dict], nfs_results: list[dict]) -> None:
    print()
    print("=" * 80)
    print("  BENCHMARK RESULTS: Boto3Storage (S3 HTTP) vs DirectMountStorage (NFS)")
    print("=" * 80)
    print()

    # Header
    print(f"{'Size':>6}  {'Operation':<18}  {'S3 (Boto3)':>12}  {'NFS (Mount)':>12}  {'Speedup':>10}")
    print("-" * 70)

    total_s3 = 0.0
    total_nfs = 0.0

    for s3r, nfsr in zip(s3_results, nfs_results):
        size = f"{s3r['size_mb']} MB"
        for op in ["upload", "download", "copy"]:
            s3_t = s3r[f"{op}_median"]
            nfs_t = nfsr[f"{op}_median"]
            total_s3 += s3_t
            total_nfs += nfs_t

            speedup = s3_t / nfs_t if nfs_t > 0 else float("inf")
            op_label = op.capitalize()
            if op == "copy":
                op_label = "Copy (handover)"

            print(f"{size:>6}  {op_label:<18}  {fmt_ms(s3_t)}  {fmt_ms(nfs_t)}  {speedup:>8.1f}x")

        print()

    print("-" * 70)
    total_speedup = total_s3 / total_nfs if total_nfs > 0 else float("inf")
    print(f"{'TOTAL':>6}  {'All operations':<18}  {fmt_ms(total_s3)}  {fmt_ms(total_nfs)}  {total_speedup:>8.1f}x")
    print()

    # Summary box
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  BEFORE: S3 HTTP API (Boto3)                               │")
    print("│    Agent A → PutObject → CopyObject → GetObject → Agent B  │")
    print("│    Every operation crosses the network (HTTP round-trip).   │")
    print("│                                                             │")
    print("│  AFTER: S3 Files Direct Mount (NFS)                        │")
    print("│    Agent A → write /mnt/s3/... → Agent B reads /mnt/s3/... │")
    print("│    All operations are local filesystem I/O. Zero network.  │")
    print("│                                                             │")
    print(f"│  Overall speedup: {total_speedup:.1f}x faster with Direct Mount{' ' * (20 - len(f'{total_speedup:.1f}'))}│")
    print("└─────────────────────────────────────────────────────────────┘")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Benchmark S3 vs NFS storage")
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=[1, 5, 25],
        help="File sizes in MB to benchmark (default: 1 5 25)",
    )
    parser.add_argument(
        "--iterations", type=int, default=3,
        help="Number of iterations per test (default: 3, uses median)",
    )
    parser.add_argument(
        "--endpoint", default="http://localhost:9000",
        help="MinIO/S3 endpoint (default: http://localhost:9000)",
    )
    parser.add_argument(
        "--bucket", default="benchmark-test",
        help="Bucket name for S3 tests (default: benchmark-test)",
    )
    args = parser.parse_args()

    print("Benchmark: Boto3Storage (S3 HTTP) vs DirectMountStorage (NFS Direct Mount)")
    print(f"  Sizes:      {args.sizes} MB")
    print(f"  Iterations: {args.iterations} (median reported)")
    print(f"  S3 endpoint: {args.endpoint}")
    print()

    # Ensure MinIO credentials are available (default: minioadmin/minioadmin)
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
    if not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"

    # Check MinIO
    if not ensure_minio_bucket(args.endpoint, args.bucket):
        print("ERROR: MinIO is not running. Start it with: docker compose up minio -d")
        sys.exit(1)

    # Create providers
    s3_provider = Boto3Storage(
        bucket=args.bucket,
        endpoint_url=args.endpoint,
    )
    nfs_provider = DirectMountStorage(
        bucket=args.bucket,
        mount_path="",  # auto temp dir
    )

    s3_results = []
    nfs_results = []

    for size_mb in args.sizes:
        # Create test file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tmp:
            test_file = Path(tmp.name)
        create_test_file(test_file, size_mb)
        print(f"Testing {size_mb} MB ...")

        try:
            prefix = f"bench/{size_mb}mb"

            # Benchmark S3 (Boto3)
            s3r = benchmark_provider(
                "S3 (Boto3)", s3_provider, test_file, size_mb,
                prefix=f"{prefix}/s3", iterations=args.iterations,
            )
            s3_results.append(s3r)

            # Benchmark NFS (Direct Mount)
            nfsr = benchmark_provider(
                "NFS (Mount)", nfs_provider, test_file, size_mb,
                prefix=f"{prefix}/nfs", iterations=args.iterations,
            )
            nfs_results.append(nfsr)

        finally:
            test_file.unlink(missing_ok=True)

    print_results(s3_results, nfs_results)


if __name__ == "__main__":
    main()
