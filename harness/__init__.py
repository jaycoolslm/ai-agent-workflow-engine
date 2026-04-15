"""
Harness Evaluation — End-to-End Quality + Performance Test Harness.

Combines the evaluation module (quality checks) with the benchmarks module
(performance measurement) into a single test harness that can be run against
any storage+runtime combination.

The harness:
  1. Seeds a workflow manifest
  2. Runs each step through the configured runtime
  3. Evaluates output quality (hallucination, completeness, structure)
  4. Measures performance (latency, throughput, overhead)
  5. Produces a unified report with pass/fail verdict

Usage:
    from harness import WorkflowHarness, HarnessConfig

    config = HarnessConfig(
        storage_backend="s3",
        runtime_backend="echo",
        bucket="test-workflows",
    )
    harness = WorkflowHarness(config)
    report = harness.run(manifest)
    print(report)
    assert report.passed
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from storage import get_storage
from storage.protocol import StorageProtocol
from runtime import get_runtime
from evaluation import OutputEvaluator, EvaluationResult
from benchmarks import (
    StorageBenchmark,
    RuntimeBenchmark,
    WorkflowBenchmark,
    BenchmarkReport,
    _compute_stats,
)


@dataclass
class HarnessConfig:
    """Configuration for a harness evaluation run."""
    storage_backend: str = "s3"
    runtime_backend: str = "echo"
    bucket: str = "harness-test"
    run_prefix: str = "harness/run_001"
    min_quality_score: float = 0.6
    max_step_seconds: float = 30.0  # Max allowed time per step
    max_handover_seconds: float = 5.0  # Max allowed file handover time
    benchmark_iterations: int = 10
    # Storage kwargs
    s3_endpoint: str = "http://localhost:9000"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"
    nfs_mount_path: str = ""
    gcp_project: str = ""


@dataclass
class StepResult:
    """Result of evaluating + benchmarking a single workflow step."""
    step_idx: int
    agent: str
    # Quality
    quality_score: float
    quality_passed: bool
    quality_issues: list[str] = field(default_factory=list)
    # Performance
    execution_seconds: float = 0.0
    handover_seconds: float = 0.0
    output_files: list[str] = field(default_factory=list)
    output_bytes: int = 0
    # Thresholds
    perf_passed: bool = True


@dataclass
class HarnessReport:
    """Full harness evaluation report."""
    workflow: str
    timestamp: str
    config: dict = field(default_factory=dict)
    steps: list[StepResult] = field(default_factory=list)
    storage_benchmark: Optional[BenchmarkReport] = None
    runtime_benchmark: Optional[BenchmarkReport] = None
    workflow_benchmark: Optional[BenchmarkReport] = None
    total_seconds: float = 0.0
    passed: bool = False
    summary: str = ""

    def __str__(self) -> str:
        lines = [
            f"\n{'='*70}",
            f"HARNESS EVALUATION REPORT",
            f"{'='*70}",
            f"  Workflow:     {self.workflow}",
            f"  Timestamp:    {self.timestamp}",
            f"  Total Time:   {self.total_seconds:.3f}s",
            f"  Verdict:      {'PASSED' if self.passed else 'FAILED'}",
            f"{'='*70}",
            "",
            "--- Step Results ---",
        ]
        for s in self.steps:
            status = "PASS" if (s.quality_passed and s.perf_passed) else "FAIL"
            lines.append(
                f"  Step {s.step_idx} ({s.agent}): "
                f"quality={s.quality_score:.3f} "
                f"exec={s.execution_seconds:.3f}s "
                f"handover={s.handover_seconds:.3f}s "
                f"files={len(s.output_files)} "
                f"bytes={s.output_bytes} "
                f"[{status}]"
            )
            if s.quality_issues:
                for issue in s.quality_issues:
                    lines.append(f"    - {issue}")

        if self.storage_benchmark:
            lines.append(str(self.storage_benchmark))
        if self.runtime_benchmark:
            lines.append(str(self.runtime_benchmark))
        if self.workflow_benchmark:
            lines.append(str(self.workflow_benchmark))

        lines.extend(["", f"Summary: {self.summary}", ""])
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "timestamp": self.timestamp,
            "total_seconds": self.total_seconds,
            "passed": self.passed,
            "summary": self.summary,
            "config": self.config,
            "steps": [
                {
                    "step_idx": s.step_idx,
                    "agent": s.agent,
                    "quality_score": s.quality_score,
                    "quality_passed": s.quality_passed,
                    "quality_issues": s.quality_issues,
                    "execution_seconds": s.execution_seconds,
                    "handover_seconds": s.handover_seconds,
                    "output_files": s.output_files,
                    "output_bytes": s.output_bytes,
                    "perf_passed": s.perf_passed,
                }
                for s in self.steps
            ],
            "storage_benchmark": self.storage_benchmark.to_dict() if self.storage_benchmark else None,
            "runtime_benchmark": self.runtime_benchmark.to_dict() if self.runtime_benchmark else None,
            "workflow_benchmark": self.workflow_benchmark.to_dict() if self.workflow_benchmark else None,
        }


class WorkflowHarness:
    """
    End-to-end quality + performance test harness.

    Runs a complete workflow with the configured storage and runtime backends,
    evaluates output quality, and measures performance.
    """

    def __init__(self, config: HarnessConfig):
        self.config = config
        self.storage = self._create_storage()
        self.runtime = self._create_runtime()
        self.evaluator = OutputEvaluator(min_score=config.min_quality_score)

    def _create_storage(self) -> StorageProtocol:
        backend = self.config.storage_backend
        if backend == "s3":
            os.environ.setdefault("AWS_ACCESS_KEY_ID", self.config.aws_access_key_id)
            os.environ.setdefault("AWS_SECRET_ACCESS_KEY", self.config.aws_secret_access_key)
            return get_storage("s3", bucket=self.config.bucket, endpoint_url=self.config.s3_endpoint)
        if backend == "nfs":
            return get_storage("nfs", bucket=self.config.bucket, mount_path=self.config.nfs_mount_path)
        if backend == "gcs":
            return get_storage("gcs", bucket=self.config.bucket, project=self.config.gcp_project)
        raise ValueError(f"Unsupported storage backend: {backend}")

    def _create_runtime(self):
        return get_runtime(self.config.runtime_backend)

    def run(self, manifest: dict, run_benchmarks: bool = True) -> HarnessReport:
        """Execute the full harness: workflow + evaluation + benchmarks."""
        t_start = time.perf_counter()
        report = HarnessReport(
            workflow=manifest.get("workflow", "unknown"),
            timestamp=datetime.now(timezone.utc).isoformat(),
            config={
                "storage_backend": self.config.storage_backend,
                "runtime_backend": self.config.runtime_backend,
                "bucket": self.config.bucket,
                "min_quality_score": self.config.min_quality_score,
                "max_step_seconds": self.config.max_step_seconds,
            },
        )

        prefix = self.config.run_prefix

        # Ensure bucket/prefix exists
        self._ensure_storage()

        # Seed manifest
        self.storage.write_json(f"{prefix}/manifest.json", manifest)

        # Run each step
        context = {}
        all_passed = True

        for step in manifest.get("steps", []):
            step_result = self._run_step(step, manifest, context, prefix)
            report.steps.append(step_result)
            if not step_result.quality_passed or not step_result.perf_passed:
                all_passed = False

        # Run benchmarks if requested
        if run_benchmarks:
            try:
                sb = StorageBenchmark(
                    self.storage,
                    prefix=f"{prefix}/bench_storage",
                    iterations=self.config.benchmark_iterations,
                )
                report.storage_benchmark = sb.run()
            except Exception as e:
                print(f"  [WARN] Storage benchmark failed: {e}")

            try:
                rb = RuntimeBenchmark(
                    self.runtime,
                    iterations=self.config.benchmark_iterations,
                )
                report.runtime_benchmark = rb.run()
            except Exception as e:
                print(f"  [WARN] Runtime benchmark failed: {e}")

            try:
                wb = WorkflowBenchmark(self.storage)
                report.workflow_benchmark = wb.run(manifest, f"{prefix}/bench_workflow")
            except Exception as e:
                print(f"  [WARN] Workflow benchmark failed: {e}")

        report.total_seconds = time.perf_counter() - t_start
        report.passed = all_passed

        # Generate summary
        n_steps = len(report.steps)
        n_passed = sum(1 for s in report.steps if s.quality_passed and s.perf_passed)
        avg_quality = sum(s.quality_score for s in report.steps) / n_steps if n_steps else 0
        total_issues = sum(len(s.quality_issues) for s in report.steps)
        report.summary = (
            f"{n_passed}/{n_steps} steps passed | "
            f"avg quality={avg_quality:.3f} | "
            f"{total_issues} issues | "
            f"total={report.total_seconds:.3f}s"
        )

        return report

    def _ensure_storage(self):
        """Create bucket if using S3."""
        if self.config.storage_backend == "s3":
            import boto3
            from botocore.config import Config
            s3 = boto3.client(
                "s3",
                endpoint_url=self.config.s3_endpoint,
                aws_access_key_id=self.config.aws_access_key_id,
                aws_secret_access_key=self.config.aws_secret_access_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            try:
                s3.head_bucket(Bucket=self.config.bucket)
            except Exception:
                s3.create_bucket(Bucket=self.config.bucket)

    def _run_step(
        self,
        step: dict,
        manifest: dict,
        context: dict,
        prefix: str,
    ) -> StepResult:
        """Run a single workflow step with evaluation and timing."""
        step_idx = step["step"]
        agent = step.get("agent", "unknown")
        instruction = step.get("instruction", "")

        print(f"\n--- Harness: Step {step_idx} ({agent}) ---")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            # Download input files (from previous step handover)
            input_prefix = f"{prefix}/step_{step_idx}/input"
            try:
                self.storage.download_prefix_to_dir(input_prefix, input_dir)
            except Exception:
                pass  # First step has no inputs

            # Build prompt
            input_files = [str(p.relative_to(input_dir)) for p in input_dir.rglob("*") if p.is_file()]
            prompt = f"## Task\n{instruction}\n"
            if context:
                prompt += f"\n## Context\n{json.dumps(context, indent=2)}\n"
            if input_files:
                prompt += f"\n## Inputs\n" + "\n".join(f"- {f}" for f in input_files) + "\n"
            prompt += f"\n## Output\nWrite files to: {output_dir}\n"

            # Execute runtime (timed)
            t_exec = time.perf_counter()
            try:
                agent_output = asyncio.run(self.runtime.execute(
                    prompt=prompt,
                    skills_dir=None,
                    output_dir=output_dir,
                ))
            except Exception as e:
                agent_output = f"ERROR: {e}"
            execution_seconds = time.perf_counter() - t_exec

            # Collect output files
            output_files = [str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file()]
            output_bytes = sum((output_dir / f).stat().st_size for f in output_files)

            # Upload outputs
            output_prefix = f"{prefix}/step_{step_idx}/output"
            self.storage.upload_dir_to_prefix(output_dir, output_prefix)

            # File handover to next step
            t_handover = time.perf_counter()
            next_idx = step_idx + 1
            if next_idx < len(manifest.get("steps", [])):
                self.storage.copy_prefix(
                    f"{output_prefix}/",
                    f"{prefix}/step_{next_idx}/input/",
                )
            handover_seconds = time.perf_counter() - t_handover

            # Update context
            context[f"step_{step_idx}"] = {
                "agent": agent,
                "summary": agent_output[:2000] if agent_output else "",
                "output_files": output_files,
            }
            self.storage.write_json(f"{prefix}/context.json", context)

            # Quality evaluation
            eval_result = self.evaluator.evaluate(
                instruction=instruction,
                output_text=agent_output or "",
                output_files=output_files,
                output_dir=output_dir,
            )

            # Performance threshold check
            perf_passed = (
                execution_seconds <= self.config.max_step_seconds
                and handover_seconds <= self.config.max_handover_seconds
            )

            if execution_seconds > self.config.max_step_seconds:
                print(f"  [PERF FAIL] Execution took {execution_seconds:.3f}s > {self.config.max_step_seconds}s")
            if handover_seconds > self.config.max_handover_seconds:
                print(f"  [PERF FAIL] Handover took {handover_seconds:.3f}s > {self.config.max_handover_seconds}s")

            print(f"  Quality:   {eval_result.score:.3f} ({'PASS' if eval_result.passed else 'FAIL'})")
            print(f"  Exec time: {execution_seconds:.3f}s")
            print(f"  Handover:  {handover_seconds:.3f}s")
            print(f"  Files:     {output_files}")

            return StepResult(
                step_idx=step_idx,
                agent=agent,
                quality_score=eval_result.score,
                quality_passed=eval_result.passed,
                quality_issues=eval_result.issues,
                execution_seconds=execution_seconds,
                handover_seconds=handover_seconds,
                output_files=output_files,
                output_bytes=output_bytes,
                perf_passed=perf_passed,
            )
