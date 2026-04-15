"""
Test: Performance Benchmarking Module.

Tests:
  1. StorageBenchmark against NFS (local filesystem)
  2. RuntimeBenchmark with echo runtime
  3. WorkflowBenchmark with NFS storage
  4. BenchmarkReport serialization
  5. StorageBenchmark against S3 (MinIO) — requires Docker

Run with:
    python test_benchmarks.py
    python -m pytest test_benchmarks.py -v
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from benchmarks import (
    StorageBenchmark,
    RuntimeBenchmark,
    WorkflowBenchmark,
    BenchmarkReport,
    BenchmarkResult,
    _compute_stats,
)
from storage.nfs import NFSStorage
from runtime.echo import EchoRuntime


def _passed(name):
    print(f"  PASS  {name}")


def _failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


# ------------------------------------------------------------------
# Test 1: StorageBenchmark with NFS (local fs)
# ------------------------------------------------------------------
def test_storage_benchmark_nfs():
    print("[1] StorageBenchmark — NFS backend")
    mount_path = tempfile.mkdtemp(prefix="bench_nfs_")
    try:
        storage = NFSStorage(bucket="bench", mount_path=mount_path)
        bench = StorageBenchmark(storage, prefix="bench/storage", iterations=5)
        report = bench.run()

        assert isinstance(report, BenchmarkReport)
        assert report.title == "Storage Backend Throughput"
        assert len(report.results) >= 8, f"Expected 8+ results, got {len(report.results)}"

        # Verify all results have valid statistics
        for r in report.results:
            assert r.iterations > 0, f"{r.name}: no iterations"
            assert r.mean_seconds >= 0, f"{r.name}: negative mean"
            assert r.ops_per_second > 0, f"{r.name}: zero ops/sec"

        # Print report
        print(str(report))
        _passed(f"NFS storage benchmark: {len(report.results)} measurements")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


# ------------------------------------------------------------------
# Test 2: RuntimeBenchmark with echo runtime
# ------------------------------------------------------------------
def test_runtime_benchmark_echo():
    print("\n[2] RuntimeBenchmark — Echo runtime")
    runtime = EchoRuntime()
    bench = RuntimeBenchmark(runtime, iterations=5)
    report = bench.run()

    assert isinstance(report, BenchmarkReport)
    assert len(report.results) == 3, f"Expected 3 results, got {len(report.results)}"

    names = [r.name for r in report.results]
    assert "execute (short prompt)" in names
    assert "execute (long prompt + context)" in names
    assert "execute (with skills)" in names

    # Echo runtime should be very fast (< 1s per iteration)
    for r in report.results:
        assert r.mean_seconds < 1.0, f"{r.name}: too slow ({r.mean_seconds:.3f}s)"

    print(str(report))
    _passed(f"Echo runtime benchmark: mean={report.results[0].mean_seconds:.4f}s")


# ------------------------------------------------------------------
# Test 3: WorkflowBenchmark with NFS
# ------------------------------------------------------------------
def test_workflow_benchmark_nfs():
    print("\n[3] WorkflowBenchmark — NFS backend")
    mount_path = tempfile.mkdtemp(prefix="bench_wf_")
    try:
        storage = NFSStorage(bucket="bench", mount_path=mount_path)
        bench = WorkflowBenchmark(storage)

        manifest = {
            "workflow": "bench-test",
            "steps": [
                {"step": 0, "agent": "sales", "instruction": "Research company"},
                {"step": 1, "agent": "finance", "instruction": "Audit company"},
            ],
        }

        report = bench.run(manifest, run_prefix="bench/workflow")

        assert isinstance(report, BenchmarkReport)
        assert len(report.results) >= 4  # manifest_write, manifest_read, step_write, handover, total

        # Verify total workflow sim exists
        total = [r for r in report.results if r.name == "total_workflow_simulation"]
        assert len(total) == 1
        assert total[0].total_seconds > 0

        print(str(report))
        _passed(f"Workflow benchmark: total={total[0].total_seconds:.4f}s")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


# ------------------------------------------------------------------
# Test 4: BenchmarkReport serialization
# ------------------------------------------------------------------
def test_report_serialization():
    print("\n[4] BenchmarkReport serialization")
    report = BenchmarkReport(
        title="Test Report",
        metadata={"backend": "nfs", "iterations": 10},
        results=[
            BenchmarkResult(
                name="test_op",
                iterations=10,
                total_seconds=1.0,
                min_seconds=0.08,
                max_seconds=0.15,
                mean_seconds=0.1,
                median_seconds=0.1,
                stddev_seconds=0.02,
                ops_per_second=10.0,
                extra={"size_bytes": 1024},
            ),
        ],
    )

    # to_dict
    d = report.to_dict()
    assert d["title"] == "Test Report"
    assert len(d["results"]) == 1
    assert d["results"][0]["name"] == "test_op"
    assert d["results"][0]["extra"]["size_bytes"] == 1024

    # JSON serializable
    json_str = json.dumps(d, indent=2)
    parsed = json.loads(json_str)
    assert parsed["title"] == "Test Report"

    # __str__
    text = str(report)
    assert "Test Report" in text
    assert "test_op" in text

    _passed("Report serializes to dict, JSON, and string")


# ------------------------------------------------------------------
# Test 5: StorageBenchmark against S3 (MinIO)
# ------------------------------------------------------------------
def test_storage_benchmark_s3():
    print("\n[5] StorageBenchmark — S3/MinIO backend")
    try:
        import boto3
        from botocore.config import Config
        from storage.s3 import S3Storage

        endpoint = os.environ.get("S3_ENDPOINT", "http://localhost:9000")

        # Set credentials for S3Storage (which reads from env)
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "minioadmin")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "minioadmin")

        # Check MinIO connectivity
        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

        bucket = "bench-test"
        try:
            s3_client.head_bucket(Bucket=bucket)
        except Exception:
            s3_client.create_bucket(Bucket=bucket)

        storage = S3Storage(bucket=bucket, endpoint_url=endpoint)
        bench = StorageBenchmark(storage, prefix="bench/s3", iterations=5)
        report = bench.run()

        assert len(report.results) >= 8

        # S3 should have measurable latency
        for r in report.results:
            assert r.iterations > 0

        # Check bandwidth for large writes
        large_write = [r for r in report.results if "1MB" in r.name and "write" in r.name]
        if large_write and large_write[0].extra.get("bandwidth_mbps"):
            bw = large_write[0].extra["bandwidth_mbps"]
            print(f"    1MB write bandwidth: {bw} MB/s")

        print(str(report))
        _passed(f"S3 storage benchmark: {len(report.results)} measurements")

    except Exception as e:
        if "ConnectTimeoutError" in str(type(e).__name__) or "Connection" in str(e):
            print(f"  SKIP  MinIO not available ({e})")
        else:
            _failed(f"S3 benchmark error: {e}")


# ------------------------------------------------------------------
# Test 6: _compute_stats utility
# ------------------------------------------------------------------
def test_compute_stats():
    print("\n[6] _compute_stats utility")
    timings = [0.1, 0.2, 0.15, 0.12, 0.18]
    result = _compute_stats("test", timings, custom_key="value")

    assert result.name == "test"
    assert result.iterations == 5
    assert result.min_seconds == 0.1
    assert result.max_seconds == 0.2
    assert abs(result.mean_seconds - 0.15) < 0.001
    assert result.median_seconds == 0.15
    assert result.stddev_seconds > 0
    assert result.ops_per_second > 0
    assert result.extra["custom_key"] == "value"

    _passed("Stats computation correct")


def main():
    print("=" * 60)
    print("BENCHMARKING MODULE TESTS")
    print("=" * 60)
    print()

    test_storage_benchmark_nfs()
    test_runtime_benchmark_echo()
    test_workflow_benchmark_nfs()
    test_report_serialization()
    test_storage_benchmark_s3()
    test_compute_stats()

    print()
    print("=" * 60)
    print("ALL BENCHMARK TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
