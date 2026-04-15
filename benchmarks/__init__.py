"""
Performance Benchmarking for the AI Agent Workflow Engine.

Measures and reports on:
  - Storage backend throughput (read/write ops, latency, bandwidth)
  - Runtime execution overhead (startup, teardown, prompt processing)
  - End-to-end workflow timing (step duration, handover latency, total time)
  - Docker container lifecycle (pull, start, execute, stop)

Usage:
    from benchmarks import StorageBenchmark, RuntimeBenchmark, WorkflowBenchmark

    # Storage throughput
    sb = StorageBenchmark(storage, prefix="bench/storage")
    report = sb.run()
    print(report)

    # Runtime overhead
    rb = RuntimeBenchmark(runtime)
    report = rb.run()
    print(report)

    # Full workflow E2E
    wb = WorkflowBenchmark(storage, router_func)
    report = wb.run(manifest)
    print(report)
"""

from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from storage.protocol import StorageProtocol


@dataclass
class BenchmarkResult:
    """Single benchmark measurement."""
    name: str
    iterations: int
    total_seconds: float
    min_seconds: float
    max_seconds: float
    mean_seconds: float
    median_seconds: float
    stddev_seconds: float
    ops_per_second: float
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"  {self.name}:\n"
            f"    iterations:  {self.iterations}\n"
            f"    total:       {self.total_seconds:.4f}s\n"
            f"    mean:        {self.mean_seconds:.4f}s\n"
            f"    median:      {self.median_seconds:.4f}s\n"
            f"    min/max:     {self.min_seconds:.4f}s / {self.max_seconds:.4f}s\n"
            f"    stddev:      {self.stddev_seconds:.4f}s\n"
            f"    ops/sec:     {self.ops_per_second:.1f}\n"
        )


def _compute_stats(name: str, timings: list[float], **extra) -> BenchmarkResult:
    """Compute statistics from a list of timing measurements."""
    n = len(timings)
    total = sum(timings)
    return BenchmarkResult(
        name=name,
        iterations=n,
        total_seconds=total,
        min_seconds=min(timings),
        max_seconds=max(timings),
        mean_seconds=statistics.mean(timings),
        median_seconds=statistics.median(timings),
        stddev_seconds=statistics.stdev(timings) if n > 1 else 0.0,
        ops_per_second=n / total if total > 0 else float('inf'),
        extra=extra,
    )


@dataclass
class BenchmarkReport:
    """Collection of benchmark results."""
    title: str
    results: list[BenchmarkResult] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def __str__(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"BENCHMARK: {self.title}",
            f"{'='*60}",
        ]
        if self.metadata:
            for k, v in self.metadata.items():
                lines.append(f"  {k}: {v}")
            lines.append("")
        for r in self.results:
            lines.append(str(r))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "metadata": self.metadata,
            "results": [
                {
                    "name": r.name,
                    "iterations": r.iterations,
                    "total_seconds": r.total_seconds,
                    "mean_seconds": r.mean_seconds,
                    "median_seconds": r.median_seconds,
                    "min_seconds": r.min_seconds,
                    "max_seconds": r.max_seconds,
                    "stddev_seconds": r.stddev_seconds,
                    "ops_per_second": r.ops_per_second,
                    "extra": r.extra,
                }
                for r in self.results
            ],
        }


class StorageBenchmark:
    """
    Benchmark storage backend throughput and latency.

    Tests:
      - Small object write (1KB JSON)
      - Small object read
      - Medium object write (100KB)
      - Medium object read
      - Large object write (1MB)
      - Large object read
      - Key listing
      - Copy operation
      - Key existence check
    """

    def __init__(
        self,
        storage: StorageProtocol,
        prefix: str = "bench/storage",
        iterations: int = 20,
    ):
        self.storage = storage
        self.prefix = prefix
        self.iterations = iterations

    def run(self) -> BenchmarkReport:
        report = BenchmarkReport(
            title="Storage Backend Throughput",
            metadata={
                "backend": type(self.storage).__name__,
                "prefix": self.prefix,
                "iterations": self.iterations,
            },
        )

        # Generate test data
        small_data = {"key": "value", "number": 42, "nested": {"a": 1}}
        medium_bytes = os.urandom(100 * 1024)  # 100KB
        large_bytes = os.urandom(1024 * 1024)  # 1MB

        # --- Small JSON write ---
        timings = []
        for i in range(self.iterations):
            key = f"{self.prefix}/small_{i}.json"
            t0 = time.perf_counter()
            self.storage.write_json(key, small_data)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("write_json (1KB)", timings, size_bytes=len(json.dumps(small_data))))

        # --- Small JSON read ---
        timings = []
        for i in range(self.iterations):
            key = f"{self.prefix}/small_{i}.json"
            t0 = time.perf_counter()
            self.storage.read_json(key)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("read_json (1KB)", timings))

        # --- Medium bytes write ---
        timings = []
        for i in range(self.iterations):
            key = f"{self.prefix}/medium_{i}.bin"
            t0 = time.perf_counter()
            self.storage.write_bytes(key, medium_bytes)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("write_bytes (100KB)", timings, size_bytes=len(medium_bytes)))

        # --- Medium bytes read ---
        timings = []
        for i in range(self.iterations):
            key = f"{self.prefix}/medium_{i}.bin"
            t0 = time.perf_counter()
            self.storage.read_bytes(key)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("read_bytes (100KB)", timings))

        # --- Large bytes write ---
        timings = []
        for i in range(min(self.iterations, 10)):  # Fewer iterations for large
            key = f"{self.prefix}/large_{i}.bin"
            t0 = time.perf_counter()
            self.storage.write_bytes(key, large_bytes)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats(
            "write_bytes (1MB)", timings,
            size_bytes=len(large_bytes),
            bandwidth_mbps=round(len(large_bytes) / (1024*1024) / statistics.mean(timings), 2) if timings else 0,
        ))

        # --- Large bytes read ---
        timings = []
        for i in range(min(self.iterations, 10)):
            key = f"{self.prefix}/large_{i}.bin"
            t0 = time.perf_counter()
            self.storage.read_bytes(key)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats(
            "read_bytes (1MB)", timings,
            bandwidth_mbps=round(len(large_bytes) / (1024*1024) / statistics.mean(timings), 2) if timings else 0,
        ))

        # --- List keys ---
        timings = []
        for _ in range(self.iterations):
            t0 = time.perf_counter()
            self.storage.list_keys(self.prefix)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("list_keys", timings))

        # --- Key exists ---
        timings = []
        key = f"{self.prefix}/small_0.json"
        for _ in range(self.iterations):
            t0 = time.perf_counter()
            self.storage.key_exists(key)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("key_exists", timings))

        # --- Copy prefix ---
        timings = []
        for i in range(min(self.iterations, 5)):
            src = f"{self.prefix}/small_0.json"
            self.storage.write_json(f"{self.prefix}/copy_src/{i}.json", small_data)
        for i in range(min(self.iterations, 5)):
            t0 = time.perf_counter()
            self.storage.copy_prefix(f"{self.prefix}/copy_src/", f"{self.prefix}/copy_dst_{i}/")
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("copy_prefix", timings))

        # Cleanup
        for key in self.storage.list_keys(self.prefix):
            try:
                self.storage.write_bytes(key, b"")  # Can't delete via protocol, overwrite
            except Exception:
                pass

        return report


class RuntimeBenchmark:
    """
    Benchmark agent runtime execution overhead.

    Tests:
      - Prompt building time
      - Execution time (with echo/mock runtime)
      - Skills loading time
    """

    def __init__(self, runtime, iterations: int = 10):
        self.runtime = runtime
        self.iterations = iterations

    def run(self) -> BenchmarkReport:
        import asyncio

        report = BenchmarkReport(
            title="Runtime Execution Overhead",
            metadata={
                "runtime": type(self.runtime).__name__,
                "iterations": self.iterations,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            # Short prompt
            short_prompt = "Write a hello world file as output.md"
            timings = []
            for _ in range(self.iterations):
                # Clear output dir
                for f in output_dir.iterdir():
                    f.unlink()
                t0 = time.perf_counter()
                asyncio.run(self.runtime.execute(
                    prompt=short_prompt,
                    skills_dir=None,
                    output_dir=output_dir,
                ))
                timings.append(time.perf_counter() - t0)
            report.results.append(_compute_stats("execute (short prompt)", timings))

            # Long prompt with context
            long_prompt = (
                "Research the company 'Grab Holdings'. "
                "Find their latest revenue figures, key business segments. "
                "Output as company_profile.md and company_data.json.\n\n"
                "## Shared Context\n"
                + json.dumps({"company": "Grab", "ticker": "GRAB", "region": "SEA"}, indent=2)
                + "\n\n## Input Files\n- prior_report.md\n- financials.json\n"
            )
            timings = []
            for _ in range(self.iterations):
                for f in output_dir.iterdir():
                    f.unlink()
                t0 = time.perf_counter()
                asyncio.run(self.runtime.execute(
                    prompt=long_prompt,
                    skills_dir=None,
                    output_dir=output_dir,
                ))
                timings.append(time.perf_counter() - t0)
            report.results.append(_compute_stats("execute (long prompt + context)", timings))

            # With skills directory
            skills_dir = Path(tmpdir) / "skills"
            skill1 = skills_dir / "research"
            skill1.mkdir(parents=True)
            (skill1 / "SKILL.md").write_text(
                "---\nname: research\ndescription: Research skill\n---\n"
                "# Research\nDo thorough research on the topic.\n"
            )
            skill2 = skills_dir / "audit"
            skill2.mkdir(parents=True)
            (skill2 / "SKILL.md").write_text(
                "---\nname: audit\ndescription: Audit skill\n---\n"
                "# Audit\nPerform financial audit.\n"
            )

            timings = []
            for _ in range(self.iterations):
                for f in output_dir.iterdir():
                    f.unlink()
                t0 = time.perf_counter()
                asyncio.run(self.runtime.execute(
                    prompt=short_prompt,
                    skills_dir=skills_dir,
                    output_dir=output_dir,
                ))
                timings.append(time.perf_counter() - t0)
            report.results.append(_compute_stats("execute (with skills)", timings))

        return report


class WorkflowBenchmark:
    """
    Benchmark end-to-end workflow execution.

    Measures:
      - Manifest read/write latency
      - Step execution time
      - File handover latency (output->input copy)
      - Context accumulation time
      - Total workflow duration
    """

    def __init__(self, storage: StorageProtocol):
        self.storage = storage

    def run(self, manifest: dict, run_prefix: str = "bench/workflow") -> BenchmarkReport:
        """Run a simulated workflow and measure all phases."""
        report = BenchmarkReport(
            title="End-to-End Workflow Timing",
            metadata={
                "workflow": manifest.get("workflow", "unknown"),
                "steps": len(manifest.get("steps", [])),
                "prefix": run_prefix,
            },
        )

        # --- Manifest write ---
        timings = []
        for _ in range(10):
            t0 = time.perf_counter()
            self.storage.write_json(f"{run_prefix}/manifest.json", manifest)
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("manifest_write", timings))

        # --- Manifest read ---
        timings = []
        for _ in range(10):
            t0 = time.perf_counter()
            self.storage.read_json(f"{run_prefix}/manifest.json")
            timings.append(time.perf_counter() - t0)
        report.results.append(_compute_stats("manifest_read", timings))

        # --- Simulate step execution with file handover ---
        step_timings = []
        handover_timings = []

        for step in manifest.get("steps", []):
            step_idx = step["step"]
            output_prefix = f"{run_prefix}/step_{step_idx}/output"

            # Simulate agent output (write files)
            t0 = time.perf_counter()
            self.storage.write_bytes(
                f"{output_prefix}/result.md",
                f"# Step {step_idx} Output\n\nGenerated content for step {step_idx}.\n".encode(),
            )
            self.storage.write_json(
                f"{output_prefix}/data.json",
                {"step": step_idx, "status": "complete", "score": 0.85},
            )
            step_timings.append(time.perf_counter() - t0)

            # Context update
            ctx_key = f"{run_prefix}/context.json"
            ctx = {}
            if self.storage.key_exists(ctx_key):
                ctx = self.storage.read_json(ctx_key)
            ctx[f"step_{step_idx}"] = {
                "agent": step.get("agent", "unknown"),
                "summary": f"Completed step {step_idx}",
            }
            self.storage.write_json(ctx_key, ctx)

            # File handover to next step
            next_idx = step_idx + 1
            if next_idx < len(manifest.get("steps", [])):
                t0 = time.perf_counter()
                self.storage.copy_prefix(
                    f"{output_prefix}/",
                    f"{run_prefix}/step_{next_idx}/input/",
                )
                handover_timings.append(time.perf_counter() - t0)

        if step_timings:
            report.results.append(_compute_stats("step_output_write", step_timings))
        if handover_timings:
            report.results.append(_compute_stats("file_handover (copy_prefix)", handover_timings))

        # --- Total workflow simulation ---
        t0 = time.perf_counter()
        # Re-run the full simulated workflow
        self.storage.write_json(f"{run_prefix}/manifest.json", manifest)
        for step in manifest.get("steps", []):
            step_idx = step["step"]
            output_prefix = f"{run_prefix}/step_{step_idx}/output"
            self.storage.write_bytes(f"{output_prefix}/result.md", b"# Output\nDone.\n")
            self.storage.write_json(f"{output_prefix}/data.json", {"done": True})
            next_idx = step_idx + 1
            if next_idx < len(manifest.get("steps", [])):
                self.storage.copy_prefix(f"{output_prefix}/", f"{run_prefix}/step_{next_idx}/input/")
        total_time = time.perf_counter() - t0
        report.results.append(BenchmarkResult(
            name="total_workflow_simulation",
            iterations=1,
            total_seconds=total_time,
            min_seconds=total_time,
            max_seconds=total_time,
            mean_seconds=total_time,
            median_seconds=total_time,
            stddev_seconds=0.0,
            ops_per_second=1.0 / total_time if total_time > 0 else float('inf'),
        ))

        return report


class ContainerBenchmark:
    """
    Benchmark Docker container lifecycle timing.

    Measures container start-to-finish time by running the echo runtime
    in a Docker container and timing the full lifecycle.
    """

    def __init__(self, image: str = "workflow-agent:local", iterations: int = 3):
        self.image = image
        self.iterations = iterations

    def run(
        self,
        bucket: str,
        run_prefix: str,
        minio_endpoint: str = "http://host.docker.internal:9000",
    ) -> BenchmarkReport:
        import subprocess

        report = BenchmarkReport(
            title="Container Lifecycle Timing",
            metadata={
                "image": self.image,
                "iterations": self.iterations,
            },
        )

        timings = []
        for i in range(self.iterations):
            cmd = [
                "docker", "run", "--rm",
                "--add-host=host.docker.internal:host-gateway",
                "-e", f"PLUGIN_NAME=sales",
                "-e", f"BUCKET={bucket}",
                "-e", f"RUN_PREFIX={run_prefix}",
                "-e", f"S3_ENDPOINT={minio_endpoint}",
                "-e", "AWS_ACCESS_KEY_ID=minioadmin",
                "-e", "AWS_SECRET_ACCESS_KEY=minioadmin",
                "-e", "AWS_DEFAULT_REGION=us-east-1",
                "-e", "AGENT_RUNTIME=echo",
                self.image,
            ]
            t0 = time.perf_counter()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            elapsed = time.perf_counter() - t0

            if result.returncode == 0:
                timings.append(elapsed)
            else:
                print(f"  [WARN] Container run {i} failed (exit {result.returncode}): {result.stderr[:200]}")

        if timings:
            report.results.append(_compute_stats("container_lifecycle", timings))
        else:
            report.results.append(BenchmarkResult(
                name="container_lifecycle",
                iterations=0,
                total_seconds=0,
                min_seconds=0,
                max_seconds=0,
                mean_seconds=0,
                median_seconds=0,
                stddev_seconds=0,
                ops_per_second=0,
                extra={"error": "All container runs failed"},
            ))

        return report
