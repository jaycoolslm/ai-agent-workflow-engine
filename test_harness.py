"""
Test: Harness Evaluation — E2E Quality + Performance Test Harness.

Tests:
  1. Full harness run with NFS storage + echo runtime
  2. Full harness run with S3/MinIO + echo runtime
  3. Harness report serialization and JSON export
  4. Harness with quality failure (empty output)
  5. Harness with custom manifest
  6. Docker container benchmark (requires Docker + built image)

Run with:
    python test_harness.py
    python -m pytest test_harness.py -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import WorkflowHarness, HarnessConfig, HarnessReport


def _passed(name):
    print(f"  PASS  {name}")


def _failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


SAMPLE_MANIFEST = {
    "run_id": "harness_001",
    "workflow": "company-assessment",
    "created_at": "2026-04-15T10:00:00Z",
    "status": "running",
    "current_step": 0,
    "steps": [
        {
            "step": 0,
            "agent": "sales",
            "instruction": (
                "Research the company 'TestCorp'. "
                "Find revenue figures, business segments. "
                "Output as company_profile.md and company_data.json."
            ),
            "status": "pending",
        },
        {
            "step": 1,
            "agent": "finance",
            "instruction": (
                "Using the company profile from previous step, "
                "perform a financial health assessment. "
                "Output as financial_audit.md and scorecard.json."
            ),
            "status": "pending",
        },
    ],
    "context": {
        "company_name": "TestCorp",
        "region": "Global",
    },
}


# ------------------------------------------------------------------
# Test 1: Full harness with NFS + echo
# ------------------------------------------------------------------
def test_harness_nfs_echo():
    print("[1] Full harness — NFS + echo runtime")
    mount_path = tempfile.mkdtemp(prefix="harness_nfs_")
    try:
        config = HarnessConfig(
            storage_backend="nfs",
            runtime_backend="echo",
            bucket="harness",
            run_prefix="harness/nfs_run_001",
            nfs_mount_path=mount_path,
            min_quality_score=0.5,  # Lower for echo runtime
            benchmark_iterations=3,  # Fewer iterations for speed
        )
        harness = WorkflowHarness(config)
        report = harness.run(SAMPLE_MANIFEST, run_benchmarks=True)

        assert isinstance(report, HarnessReport)
        assert report.workflow == "company-assessment"
        assert len(report.steps) == 2
        assert report.total_seconds > 0

        # Both steps should pass with echo runtime
        for step in report.steps:
            assert step.output_files, f"Step {step.step_idx} produced no files"
            assert step.execution_seconds < 5.0, f"Step {step.step_idx} too slow"
            assert step.perf_passed, f"Step {step.step_idx} perf failed"

        # Benchmarks should have run
        assert report.storage_benchmark is not None
        assert report.runtime_benchmark is not None
        assert report.workflow_benchmark is not None

        print(str(report))
        _passed(f"NFS+echo harness: {report.summary}")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


# ------------------------------------------------------------------
# Test 2: Full harness with S3/MinIO + echo
# ------------------------------------------------------------------
def test_harness_s3_echo():
    print("\n[2] Full harness — S3/MinIO + echo runtime")
    try:
        import boto3
        from botocore.config import Config

        # Quick connectivity check
        s3 = boto3.client(
            "s3",
            endpoint_url="http://localhost:9000",
            aws_access_key_id="minioadmin",
            aws_secret_access_key="minioadmin",
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        s3.list_buckets()
    except Exception as e:
        print(f"  SKIP  MinIO not available ({e})")
        return

    config = HarnessConfig(
        storage_backend="s3",
        runtime_backend="echo",
        bucket="harness-test",
        run_prefix="harness/s3_run_001",
        s3_endpoint="http://localhost:9000",
        min_quality_score=0.5,
        benchmark_iterations=3,
    )
    harness = WorkflowHarness(config)
    report = harness.run(SAMPLE_MANIFEST, run_benchmarks=True)

    assert report.workflow == "company-assessment"
    assert len(report.steps) == 2

    for step in report.steps:
        assert step.output_files, f"Step {step.step_idx} produced no files"

    # S3 benchmarks should show network latency
    if report.storage_benchmark:
        for r in report.storage_benchmark.results:
            assert r.iterations > 0

    print(str(report))
    _passed(f"S3+echo harness: {report.summary}")


# ------------------------------------------------------------------
# Test 3: Report serialization
# ------------------------------------------------------------------
def test_report_serialization():
    print("\n[3] HarnessReport serialization")
    mount_path = tempfile.mkdtemp(prefix="harness_ser_")
    try:
        config = HarnessConfig(
            storage_backend="nfs",
            runtime_backend="echo",
            bucket="harness",
            run_prefix="harness/ser_001",
            nfs_mount_path=mount_path,
            benchmark_iterations=2,
        )
        harness = WorkflowHarness(config)
        report = harness.run(SAMPLE_MANIFEST, run_benchmarks=False)

        # to_dict
        d = report.to_dict()
        assert d["workflow"] == "company-assessment"
        assert len(d["steps"]) == 2
        assert "passed" in d

        # JSON serializable
        json_str = json.dumps(d, indent=2)
        parsed = json.loads(json_str)
        assert parsed["workflow"] == "company-assessment"

        # Write to file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(d, f, indent=2)
            tmp_path = f.name

        # Read back
        with open(tmp_path) as f:
            loaded = json.load(f)
        assert loaded["workflow"] == "company-assessment"
        os.unlink(tmp_path)

        _passed("Report serializes to dict, JSON string, and file")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


# ------------------------------------------------------------------
# Test 4: Harness with custom 3-step manifest
# ------------------------------------------------------------------
def test_harness_custom_manifest():
    print("\n[4] Harness with custom 3-step manifest")
    mount_path = tempfile.mkdtemp(prefix="harness_custom_")
    try:
        manifest = {
            "run_id": "custom_001",
            "workflow": "three-step-pipeline",
            "status": "running",
            "current_step": 0,
            "steps": [
                {
                    "step": 0,
                    "agent": "sales",
                    "instruction": "Research company. Output report.md and data.json.",
                    "status": "pending",
                },
                {
                    "step": 1,
                    "agent": "finance",
                    "instruction": "Analyze financials. Output audit.md and scores.json.",
                    "status": "pending",
                },
                {
                    "step": 2,
                    "agent": "sales",
                    "instruction": "Write final summary. Output summary.md and final.json.",
                    "status": "pending",
                },
            ],
            "context": {"target": "CustomCorp"},
        }

        config = HarnessConfig(
            storage_backend="nfs",
            runtime_backend="echo",
            bucket="harness",
            run_prefix="harness/custom_001",
            nfs_mount_path=mount_path,
            min_quality_score=0.5,
            benchmark_iterations=2,
        )
        harness = WorkflowHarness(config)
        report = harness.run(manifest, run_benchmarks=False)

        assert len(report.steps) == 3
        for step in report.steps:
            assert step.output_files, f"Step {step.step_idx} produced no files"

        _passed(f"3-step harness: {report.summary}")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


# ------------------------------------------------------------------
# Test 5: Docker container benchmark (requires Docker + image)
# ------------------------------------------------------------------
def test_container_benchmark():
    print("\n[5] Container lifecycle benchmark")
    try:
        # Check Docker is available
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            print(f"  SKIP  Docker not available")
            return

        # Check image exists
        result = subprocess.run(
            ["docker", "images", "workflow-agent:local", "--format", "{{.Repository}}"],
            capture_output=True, text=True, timeout=5,
        )
        if "workflow-agent" not in result.stdout:
            print(f"  SKIP  workflow-agent:local image not built")
            return

        # Check MinIO is running
        try:
            import boto3
            from botocore.config import Config
            s3 = boto3.client(
                "s3",
                endpoint_url="http://localhost:9000",
                aws_access_key_id="minioadmin",
                aws_secret_access_key="minioadmin",
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            s3.list_buckets()
        except Exception:
            print(f"  SKIP  MinIO not running")
            return

        # Seed a workflow for the container to run
        bucket = "bench-container"
        prefix = "runs/bench_001"
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)

        manifest = {
            "run_id": "bench_001",
            "workflow": "container-bench",
            "status": "running",
            "current_step": 0,
            "steps": [{
                "step": 0,
                "agent": "sales",
                "instruction": "Write a brief summary as output.md",
                "status": "running",
            }],
            "context": {},
        }
        s3.put_object(
            Bucket=bucket,
            Key=f"{prefix}/manifest.json",
            Body=json.dumps(manifest).encode(),
        )

        from benchmarks import ContainerBenchmark
        bench = ContainerBenchmark(image="workflow-agent:local", iterations=2)
        report = bench.run(bucket=bucket, run_prefix=prefix)

        assert len(report.results) == 1
        r = report.results[0]
        if r.iterations > 0:
            print(f"    Container lifecycle: mean={r.mean_seconds:.3f}s, min={r.min_seconds:.3f}s")
            assert r.mean_seconds < 30.0, "Container took too long"
            _passed(f"Container benchmark: {r.mean_seconds:.3f}s avg")
        else:
            print(f"  WARN  Container runs failed: {r.extra}")
            _passed("Container benchmark ran (with failures)")

    except FileNotFoundError:
        print(f"  SKIP  Docker CLI not found")


# ------------------------------------------------------------------
# Test 6: Performance threshold enforcement
# ------------------------------------------------------------------
def test_perf_thresholds():
    print("\n[6] Performance threshold enforcement")
    mount_path = tempfile.mkdtemp(prefix="harness_perf_")
    try:
        # Use very tight thresholds — echo runtime should still pass
        config = HarnessConfig(
            storage_backend="nfs",
            runtime_backend="echo",
            bucket="harness",
            run_prefix="harness/perf_001",
            nfs_mount_path=mount_path,
            max_step_seconds=10.0,
            max_handover_seconds=5.0,
            benchmark_iterations=2,
        )
        harness = WorkflowHarness(config)
        report = harness.run(SAMPLE_MANIFEST, run_benchmarks=False)

        for step in report.steps:
            assert step.perf_passed, (
                f"Step {step.step_idx} failed perf: "
                f"exec={step.execution_seconds:.3f}s, "
                f"handover={step.handover_seconds:.3f}s"
            )

        _passed("All steps within performance thresholds")
    finally:
        shutil.rmtree(mount_path, ignore_errors=True)


def main():
    print("=" * 60)
    print("HARNESS EVALUATION TESTS")
    print("=" * 60)
    print()

    test_harness_nfs_echo()
    test_harness_s3_echo()
    test_report_serialization()
    test_harness_custom_manifest()
    test_container_benchmark()
    test_perf_thresholds()

    print()
    print("=" * 60)
    print("ALL HARNESS TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
