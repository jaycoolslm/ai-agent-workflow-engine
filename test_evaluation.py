"""
Test: AI output quality evaluator.

Tests:
  1. Completeness check
  2. Structure check
  3. Hallucination detection
  4. Full workflow evaluation
  5. Edge cases

Run with:
    python test_evaluation.py
"""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from evaluation import OutputEvaluator, evaluate_workflow_outputs
from storage.nfs import NFSStorage


def test_passed(name):
    print(f"  PASS  {name}")


def test_failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


def main():
    print("=" * 60)
    print("EVALUATION MODULE TESTS")
    print("=" * 60)
    print()

    evaluator = OutputEvaluator(min_score=0.6)

    # ------------------------------------------------------------------
    # Test 1: Good output passes
    # ------------------------------------------------------------------
    print("[1] Good output passes evaluation")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        (output_dir / "company_profile.md").write_text(
            "# Grab Holdings Profile\n\n## Overview\nGrab is a leading superapp in Southeast Asia.\n\n## Revenue\nRevenue: $2.36B in 2025.\n\n## Segments\n- Deliveries\n- Mobility\n- Financial Services\n",
            encoding="utf-8",
        )
        (output_dir / "company_data.json").write_text(
            json.dumps({"revenue": 2360000000, "growth": 0.17, "region": "SEA"}),
            encoding="utf-8",
        )

        result = evaluator.evaluate(
            instruction="Research Grab Holdings. Output company_profile.md and company_data.json.",
            output_text="Researched Grab Holdings. Revenue $2.36B. Strong growth in SEA.",
            output_files=["company_profile.md", "company_data.json"],
            output_dir=output_dir,
        )

        assert result.passed, f"Should pass, got score={result.score}, issues={result.issues}"
        assert result.score >= 0.7
        test_passed(f"Good output scored {result.score:.2f}")

    # ------------------------------------------------------------------
    # Test 2: Empty output fails
    # ------------------------------------------------------------------
    print("\n[2] Empty output fails evaluation")
    result = evaluator.evaluate(
        instruction="Research Grab Holdings. Output company_profile.md.",
        output_text="",
        output_files=[],
    )
    assert not result.passed
    assert result.score <= 0.6
    test_passed(f"Empty output scored {result.score:.2f} (correctly failed)")

    # ------------------------------------------------------------------
    # Test 3: Hallucination detection
    # ------------------------------------------------------------------
    print("\n[3] Hallucination signal detection")
    hallucinatory_text = (
        "Based on my training data, Grab Holdings revenue is $10B. "
        "I cannot verify this information as of my last knowledge cutoff. "
        "See https://example.com/fake-report for details."
    )
    result = evaluator.evaluate(
        instruction="Research Grab Holdings. Output report.md.",
        output_text=hallucinatory_text,
        output_files=["report.md"],
    )
    assert len(result.issues) > 0
    assert any("uncertainty" in i.lower() or "fabricated" in i.lower() for i in result.issues)
    test_passed(f"Detected {len(result.issues)} issues in hallucinatory output")

    # ------------------------------------------------------------------
    # Test 4: Invalid JSON detection
    # ------------------------------------------------------------------
    print("\n[4] Invalid JSON file detection")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        (output_dir / "data.json").write_text("{ invalid json }", encoding="utf-8")
        (output_dir / "report.md").write_text("# Good Report\n\nContent here that is reasonable.", encoding="utf-8")

        result = evaluator.evaluate(
            instruction="Output data.json and report.md",
            output_text="Generated report and data.",
            output_files=["data.json", "report.md"],
            output_dir=output_dir,
        )
        assert any("Invalid JSON" in i for i in result.issues)
        test_passed("Detected invalid JSON file")

    # ------------------------------------------------------------------
    # Test 5: Workflow-level evaluation with NFS storage
    # ------------------------------------------------------------------
    print("\n[5] Workflow-level evaluation with NFS storage")
    mount_path = tempfile.mkdtemp(prefix="eval_test_")
    try:
        storage = NFSStorage(bucket="test", mount_path=mount_path)
        prefix = "runs/eval_001"

        # Set up completed workflow
        manifest = {
            "run_id": "eval_001",
            "status": "complete",
            "current_step": 1,
            "steps": [
                {
                    "step": 0,
                    "agent": "sales",
                    "instruction": "Research TestCorp. Output company_profile.md and company_data.json.",
                    "status": "complete",
                },
                {
                    "step": 1,
                    "agent": "finance",
                    "instruction": "Output financial_audit.md and scorecard.json.",
                    "status": "complete",
                },
            ],
        }
        storage.write_json(f"{prefix}/manifest.json", manifest)

        # Step 0 outputs
        storage.write_bytes(
            f"{prefix}/step_0/output/company_profile.md",
            b"# TestCorp\n\n## Overview\nA test company.\n",
        )
        storage.write_json(
            f"{prefix}/step_0/output/company_data.json",
            {"revenue": 100_000_000},
        )

        # Step 1 outputs
        storage.write_bytes(
            f"{prefix}/step_1/output/financial_audit.md",
            b"# Financial Audit\n\n## Revenue\nRevenue is $100M.\n",
        )
        storage.write_json(
            f"{prefix}/step_1/output/scorecard.json",
            {"revenue_growth": 7, "profitability": 5},
        )

        # Context
        storage.write_json(f"{prefix}/context.json", {
            "step_0": {"agent": "sales", "summary": "Researched TestCorp. Revenue $100M."},
            "step_1": {"agent": "finance", "summary": "Financial audit complete. Score 7/10 growth."},
        })

        results = evaluate_workflow_outputs(manifest, storage, prefix)
        assert 0 in results
        assert 1 in results
        for step_idx, res in results.items():
            print(f"    Step {step_idx}: score={res['score']:.2f}, passed={res['passed']}")
        test_passed("Workflow-level evaluation completed")

    finally:
        shutil.rmtree(mount_path, ignore_errors=True)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL 5 EVALUATION TESTS PASSED")
    print("=" * 60)
    print()
    print("The evaluator checks:")
    print("  - Output completeness (files produced, content length)")
    print("  - Structure quality (valid JSON, markdown headings)")
    print("  - Internal consistency (cross-file number matching)")
    print("  - Hallucination signals (uncertainty phrases, fake URLs)")


if __name__ == "__main__":
    main()
