#!/usr/bin/env python3
"""
Harness Evaluation — Agent Quality Control.

Triggers the full E2E workflow (sample-manifest Sales → Finance) using the
Echo runtime, then evaluates the final outputs with heuristic "LLM-as-judge"
checks for:

  1. Data Completeness — are expected JSON keys and markdown headings present?
  2. Agent Faithfulness — did the Finance agent consume the Sales agent's output?
  3. Output Structure — are JSON/markdown files well-formed and substantial?

Prints a clean "Evaluation Scorecard" to the terminal and appends a summary
to PERFORMANCE_REPORT.md.

Usage:
    python evaluate_harness_quality.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.nfs import NFSStorage
from runtime.echo import EchoRuntime
from entrypoint import build_prompt


# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    score: float          # 0.0 – 1.0
    max_score: float = 1.0
    notes: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return (self.score / self.max_score) * 100 if self.max_score else 0


@dataclass
class StepEval:
    step: int
    agent: str
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def overall(self) -> float:
        if not self.dimensions:
            return 0.0
        return sum(d.score for d in self.dimensions) / sum(d.max_score for d in self.dimensions)


@dataclass
class Scorecard:
    steps: list[StepEval] = field(default_factory=list)
    wall_clock_seconds: float = 0.0

    @property
    def overall(self) -> float:
        if not self.steps:
            return 0.0
        return sum(s.overall for s in self.steps) / len(self.steps)

    @property
    def passed(self) -> bool:
        return self.overall >= 0.60


# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

def _eval_completeness(output_dir: Path, expected_files: list[str]) -> DimensionScore:
    """Check that every expected file exists and has minimum content."""
    score = 1.0
    notes: list[str] = []

    for fname in expected_files:
        fpath = output_dir / fname
        if not fpath.exists():
            notes.append(f"MISSING file: {fname}")
            score -= 0.25
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace")
        if len(content.strip()) < 20:
            notes.append(f"TOO SHORT: {fname} ({len(content)} chars)")
            score -= 0.15

        # JSON specific: check for expected keys
        if fname.endswith(".json"):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and len(data) < 2:
                    notes.append(f"FEW KEYS in {fname} ({len(data)} keys)")
                    score -= 0.1
            except json.JSONDecodeError:
                notes.append(f"INVALID JSON: {fname}")
                score -= 0.2

        # Markdown specific: check for headings
        if fname.endswith(".md"):
            headings = re.findall(r"^#{1,3}\s+.+", content, re.MULTILINE)
            if not headings:
                notes.append(f"NO HEADINGS in {fname}")
                score -= 0.1

    return DimensionScore(
        name="Data Completeness",
        score=max(0.0, min(1.0, score)),
        notes=notes,
    )


def _eval_faithfulness(
    step_idx: int,
    output_dir: Path,
    prev_output_dir: Path | None,
    instruction: str,
) -> DimensionScore:
    """Check whether the agent faithfully consumed prior step's output."""
    notes: list[str] = []
    score = 1.0

    if step_idx == 0 or prev_output_dir is None:
        notes.append("First step — no prior output to cross-reference.")
        return DimensionScore(name="Agent Faithfulness", score=1.0, notes=notes)

    # Gather previous step's file names
    prev_files = [f.name for f in prev_output_dir.iterdir() if f.is_file()] if prev_output_dir.exists() else []
    if not prev_files:
        notes.append("No prior step files found — skipping faithfulness check.")
        return DimensionScore(name="Agent Faithfulness", score=0.8, notes=notes)

    # Read current step output text
    cur_text = ""
    for fpath in output_dir.iterdir():
        if fpath.is_file():
            cur_text += fpath.read_text(encoding="utf-8", errors="replace") + "\n"

    # Check if current step references/mentions data from previous step
    # For Echo runtime we check that prompt context was injected
    has_reference = False
    for prev_file in prev_files:
        if prev_file in cur_text or prev_file.replace(".json", "").replace(".md", "") in cur_text:
            has_reference = True
            break

    # Check if instruction mentions "previous step"
    if re.search(r"previous\s+step|from\s+the\s+.*step|using\s+the\s+company", instruction, re.IGNORECASE):
        notes.append("Instruction references prior step output.")
        if not has_reference:
            notes.append("WARNING: Current output does not reference prior files.")
            score -= 0.2

    # Check if prior output files were copied into this step's input
    input_dir = output_dir.parent / "input"
    if input_dir.exists():
        input_files = [f.name for f in input_dir.iterdir() if f.is_file()]
        overlap = set(prev_files) & set(input_files)
        if overlap:
            notes.append(f"Input contains prior files: {list(overlap)}")
        else:
            notes.append("Prior output NOT found in current input.")
            score -= 0.3

    return DimensionScore(name="Agent Faithfulness", score=max(0.0, score), notes=notes)


def _eval_structure(output_dir: Path) -> DimensionScore:
    """Evaluate output file structure quality."""
    notes: list[str] = []
    score = 1.0
    n_files = 0

    for fpath in output_dir.iterdir():
        if not fpath.is_file():
            continue
        n_files += 1
        content = fpath.read_text(encoding="utf-8", errors="replace")

        if fpath.suffix == ".json":
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    notes.append(f"{fpath.name}: valid JSON, {len(data)} keys")
                elif isinstance(data, list):
                    notes.append(f"{fpath.name}: valid JSON array, {len(data)} items")
                else:
                    notes.append(f"{fpath.name}: valid JSON (scalar)")
            except json.JSONDecodeError as e:
                notes.append(f"{fpath.name}: INVALID JSON — {e}")
                score -= 0.25

        elif fpath.suffix == ".md":
            headings = re.findall(r"^#{1,3}\s+.+", content, re.MULTILINE)
            word_count = len(content.split())
            notes.append(f"{fpath.name}: {len(headings)} headings, {word_count} words")
            if word_count < 10:
                notes.append(f"  WARNING: very short markdown ({word_count} words)")
                score -= 0.15
        else:
            notes.append(f"{fpath.name}: {len(content)} bytes")

    if n_files == 0:
        notes.append("NO output files at all!")
        score = 0.0

    return DimensionScore(name="Output Structure", score=max(0.0, score), notes=notes)


# ---------------------------------------------------------------------------
# Workflow runner (local, no Docker)
# ---------------------------------------------------------------------------

async def _run_workflow_local(
    manifest: dict,
    storage: NFSStorage,
    runtime: EchoRuntime,
    run_prefix: str,
) -> dict[int, Path]:
    """Run the full workflow in-process and return per-step output dirs."""
    storage.write_json(f"{run_prefix}/manifest.json", manifest)
    storage.write_json(f"{run_prefix}/context.json", manifest.get("context", {}))

    step_outputs: dict[int, Path] = {}

    for step in manifest["steps"]:
        step_idx = step["step"]
        print(f"\n  Running step {step_idx}: {step['agent']} ...")

        # Prepare dirs
        input_dir = Path(tempfile.mkdtemp(prefix=f"eval_input_{step_idx}_"))
        output_dir = Path(tempfile.mkdtemp(prefix=f"eval_output_{step_idx}_"))

        # Download input
        input_prefix = f"{run_prefix}/step_{step_idx}/input"
        storage.download_prefix_to_dir(input_prefix, input_dir)

        # Build prompt
        context = {}
        ctx_key = f"{run_prefix}/context.json"
        if storage.key_exists(ctx_key):
            context = storage.read_json(ctx_key)

        prompt = build_prompt(step["instruction"], input_dir, output_dir, context)

        # Execute
        result = await runtime.execute(
            prompt=prompt,
            skills_dir=None,
            output_dir=output_dir,
        )

        # Upload outputs
        output_prefix = f"{run_prefix}/step_{step_idx}/output"
        storage.upload_dir_to_prefix(output_dir, output_prefix)

        # Copy output → next step input
        next_idx = step_idx + 1
        if next_idx < len(manifest["steps"]):
            next_input_prefix = f"{run_prefix}/step_{next_idx}/input"
            storage.copy_prefix(
                f"{run_prefix}/step_{step_idx}/output/",
                f"{run_prefix}/step_{next_idx}/input/",
            )

        # Update context
        output_files = [f.name for f in output_dir.iterdir() if f.is_file()]
        context[f"step_{step_idx}"] = {
            "agent": step["agent"],
            "summary": result[:500],
            "output_files": output_files,
        }
        storage.write_json(ctx_key, context)

        step_outputs[step_idx] = output_dir

    return step_outputs


# ---------------------------------------------------------------------------
# Scorecard rendering
# ---------------------------------------------------------------------------

def _print_scorecard(sc: Scorecard) -> str:
    lines = [
        "",
        "=" * 80,
        "  EVALUATION SCORECARD — Agent Quality Control",
        "=" * 80,
        "",
    ]

    for step_eval in sc.steps:
        lines.append(f"  Step {step_eval.step}: {step_eval.agent}")
        lines.append(f"  {'—' * 50}")
        for d in step_eval.dimensions:
            bar_len = int(d.pct / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"    {d.name:<25} [{bar}] {d.pct:5.1f}%")
            for note in d.notes:
                lines.append(f"      • {note}")
        lines.append(f"    {'─' * 45}")
        lines.append(f"    Overall: {step_eval.overall * 100:.1f}%")
        lines.append("")

    verdict = "PASS ✓" if sc.passed else "FAIL ✗"
    lines.extend([
        f"  {'━' * 50}",
        f"  OVERALL SCORE: {sc.overall * 100:.1f}%  [{verdict}]",
        f"  Wall-clock time: {sc.wall_clock_seconds:.2f}s",
        f"  {'━' * 50}",
        "",
    ])

    text = "\n".join(lines)
    print(text)
    return text


def _append_to_report(sc: Scorecard, report_path: str = "PERFORMANCE_REPORT.md") -> None:
    """Append scorecard summary to PERFORMANCE_REPORT.md."""
    md = f"""
---

## Agent Quality Evaluation Scorecard

| Step | Agent | Completeness | Faithfulness | Structure | Overall |
|:----:|:-----:|:------------:|:------------:|:---------:|:-------:|
"""
    for s in sc.steps:
        dims = {d.name: d for d in s.dimensions}
        comp = dims.get("Data Completeness")
        faith = dims.get("Agent Faithfulness")
        struct = dims.get("Output Structure")
        md += (
            f"| {s.step} | {s.agent} "
            f"| {comp.pct:.0f}% " if comp else "| — "
            f"| {faith.pct:.0f}% " if faith else "| — "
            f"| {struct.pct:.0f}% " if struct else "| — "
            f"| **{s.overall * 100:.1f}%** |\n"
        )

    verdict = "**PASS**" if sc.passed else "**FAIL**"
    md += f"""
**Overall Score:** {sc.overall * 100:.1f}% — {verdict}

**Wall-clock time:** {sc.wall_clock_seconds:.2f}s

### Dimension Details

"""
    for s in sc.steps:
        md += f"#### Step {s.step}: {s.agent}\n\n"
        for d in s.dimensions:
            md += f"- **{d.name}**: {d.pct:.1f}%\n"
            for note in d.notes:
                md += f"  - {note}\n"
        md += "\n"

    # Append to existing report or create new section
    rpath = Path(report_path)
    if rpath.exists():
        existing = rpath.read_text(encoding="utf-8")
        rpath.write_text(existing + md, encoding="utf-8")
        print(f"  Appended evaluation summary to {report_path}")
    else:
        rpath.write_text(f"# Performance Report\n{md}", encoding="utf-8")
        print(f"  Created {report_path} with evaluation summary")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("  HARNESS EVALUATION — Agent Quality Control")
    print("=" * 80)

    # Load sample manifest
    manifest_path = Path(__file__).parent / "sample-manifest.json"
    if not manifest_path.exists():
        print(f"  ERROR: {manifest_path} not found")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"  Workflow: {manifest['workflow']}")
    print(f"  Steps:    {len(manifest['steps'])}")
    print()

    # Set up local NFS storage + Echo runtime
    tmpdir = tempfile.mkdtemp(prefix="harness_eval_")
    storage = NFSStorage(bucket="eval", mount_path=tmpdir)
    runtime = EchoRuntime()
    run_prefix = "runs/eval_001"

    t0 = time.perf_counter()

    # Run workflow
    step_outputs = asyncio.run(
        _run_workflow_local(manifest, storage, runtime, run_prefix)
    )

    wall_clock = time.perf_counter() - t0

    # Evaluate each step
    sc = Scorecard(wall_clock_seconds=wall_clock)

    for step in manifest["steps"]:
        step_idx = step["step"]
        output_dir = step_outputs.get(step_idx)
        if not output_dir or not output_dir.exists():
            continue

        # Expected files from instruction
        expected = re.findall(r'\b([\w\-]+\.(?:md|json))\b', step["instruction"])
        expected = list(dict.fromkeys(expected))  # dedupe

        # Previous step output dir
        prev_output = step_outputs.get(step_idx - 1)

        dims = [
            _eval_completeness(output_dir, expected),
            _eval_faithfulness(step_idx, output_dir, prev_output, step["instruction"]),
            _eval_structure(output_dir),
        ]

        sc.steps.append(StepEval(step=step_idx, agent=step["agent"], dimensions=dims))

    # Print scorecard
    _print_scorecard(sc)

    # Append to PERFORMANCE_REPORT.md
    _append_to_report(sc)

    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)
    for d in step_outputs.values():
        shutil.rmtree(d, ignore_errors=True)

    print("\n  EVALUATION COMPLETE")
    print("=" * 80)
    return 0 if sc.passed else 1


if __name__ == "__main__":
    sys.exit(main())
