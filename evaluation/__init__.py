"""
AI Output Quality Evaluator.

Validates that agent outputs are factual, complete, and well-structured.
Helps detect hallucinations and ensure quality in multi-agent workflows.

Usage:
    from evaluation import OutputEvaluator

    evaluator = OutputEvaluator()
    result = evaluator.evaluate(
        instruction="Research Grab Holdings",
        output_text="...",
        output_files=["company_profile.md", "company_data.json"],
    )
    print(result.score, result.issues)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EvaluationResult:
    score: float  # 0.0 to 1.0
    passed: bool
    issues: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class OutputEvaluator:
    """
    Evaluates agent outputs for quality, completeness, and potential hallucinations.
    """

    def __init__(self, min_score: float = 0.6):
        self.min_score = min_score

    def evaluate(
        self,
        instruction: str,
        output_text: str,
        output_files: list[str],
        output_dir: Optional[Path] = None,
    ) -> EvaluationResult:
        """Run all evaluation checks and return an aggregated result."""
        completeness = self._check_completeness(instruction, output_text, output_files)
        structure = self._check_structure(output_text, output_files, output_dir)
        consistency = self._check_consistency(output_text, output_dir)
        hallucination = self._check_hallucination_signals(output_text)

        # Weighted average: completeness is the most important signal
        weights = [0.4, 0.2, 0.15, 0.25]
        checks = [completeness, structure, consistency, hallucination]
        total_score = sum(w * c.score for w, c in zip(weights, checks))

        all_issues = []
        all_metrics = {}
        for c in checks:
            all_issues.extend(c.issues)
            all_metrics.update(c.metrics)

        return EvaluationResult(
            score=round(total_score, 3),
            passed=total_score > self.min_score,
            issues=all_issues,
            metrics=all_metrics,
        )

    def _check_completeness(
        self,
        instruction: str,
        output_text: str,
        output_files: list[str],
    ) -> EvaluationResult:
        """Check if the output addresses the instruction and produces expected files."""
        issues = []
        score = 1.0

        # Check if expected output files are mentioned in instruction
        expected_files = re.findall(r'[\w-]+\.\w+', instruction)
        if expected_files:
            missing = [f for f in expected_files if f not in " ".join(output_files)]
            if missing:
                issues.append(f"Missing expected files: {missing}")
                score -= 0.3 * len(missing) / len(expected_files)

        # Check if output is non-empty
        if not output_text or len(output_text.strip()) < 50:
            issues.append("Output is too short (< 50 chars)")
            score -= 0.5

        # Check if no files were produced — critical failure
        if not output_files:
            issues.append("No output files produced")
            score = 0.0

        return EvaluationResult(
            score=max(0.0, score),
            passed=score >= self.min_score,
            issues=issues,
            metrics={"completeness_score": max(0.0, score), "files_produced": len(output_files)},
        )

    def _check_structure(
        self,
        output_text: str,
        output_files: list[str],
        output_dir: Optional[Path],
    ) -> EvaluationResult:
        """Check if output files are well-structured."""
        issues = []
        score = 1.0

        if output_dir and output_dir.exists():
            for fname in output_files:
                fpath = output_dir / fname
                if not fpath.exists():
                    continue

                content = fpath.read_text(encoding="utf-8", errors="replace")

                # Check JSON files are valid
                if fname.endswith(".json"):
                    try:
                        data = json.loads(content)
                        if not data:
                            issues.append(f"{fname}: JSON is empty")
                            score -= 0.2
                    except json.JSONDecodeError as e:
                        issues.append(f"{fname}: Invalid JSON — {e}")
                        score -= 0.3

                # Check markdown files have content
                elif fname.endswith(".md"):
                    if len(content.strip()) < 100:
                        issues.append(f"{fname}: Markdown file too short (< 100 chars)")
                        score -= 0.2
                    if not re.search(r'^#', content, re.MULTILINE):
                        issues.append(f"{fname}: Markdown file has no headings")
                        score -= 0.1

        return EvaluationResult(
            score=max(0.0, score),
            passed=score >= self.min_score,
            issues=issues,
            metrics={"structure_score": score},
        )

    def _check_consistency(
        self,
        output_text: str,
        output_dir: Optional[Path],
    ) -> EvaluationResult:
        """Check for internal consistency between output files."""
        issues = []
        score = 1.0

        if not output_dir or not output_dir.exists():
            return EvaluationResult(score=1.0, passed=True, metrics={"consistency_score": 1.0})

        # Collect data from JSON files
        json_data = {}
        for fpath in output_dir.glob("*.json"):
            try:
                json_data[fpath.name] = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        # Collect text from markdown files
        md_texts = {}
        for fpath in output_dir.glob("*.md"):
            try:
                md_texts[fpath.name] = fpath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass

        # Cross-reference: numbers in JSON should appear in markdown
        for json_name, data in json_data.items():
            if isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(value, (int, float)) and value > 0:
                        found = False
                        for md_text in md_texts.values():
                            if str(value) in md_text or str(int(value)) in md_text:
                                found = True
                                break
                        # Don't penalize too heavily — some numbers are intermediate
                        if not found and value > 1000:
                            issues.append(
                                f"Number {key}={value} in {json_name} not found in markdown"
                            )

        if len(issues) > 3:
            score -= 0.3
        elif len(issues) > 0:
            score -= 0.1

        return EvaluationResult(
            score=max(0.0, score),
            passed=score >= self.min_score,
            issues=issues,
            metrics={"consistency_score": score},
        )

    def _check_hallucination_signals(self, output_text: str) -> EvaluationResult:
        """
        Detect common hallucination signals in agent output.

        Heuristic-based checks — not a replacement for human review,
        but catches obvious red flags.
        """
        issues = []
        score = 1.0

        # Check for "I don't know" / uncertainty hedging that contradicts claims
        uncertainty_phrases = [
            r"I (?:don't|do not) (?:know|have access)",
            r"I (?:cannot|can't) (?:verify|confirm|access)",
            r"(?:my|the) training (?:data|cutoff)",
            r"as of my (?:last|knowledge) (?:update|cutoff)",
            r"I (?:was|am) unable to (?:find|locate|access)",
        ]
        for pattern in uncertainty_phrases:
            if re.search(pattern, output_text, re.IGNORECASE):
                issues.append(f"Uncertainty detected: '{pattern}' found in output")
                score -= 0.15

        # Check for fabricated-looking URLs
        url_pattern = re.findall(r'https?://[^\s\)]+', output_text)
        for url in url_pattern:
            # Suspiciously specific fake-looking URLs
            if re.search(r'example\.com|fake|placeholder|Lorem', url, re.IGNORECASE):
                issues.append(f"Potentially fabricated URL: {url}")
                score -= 0.1

        # Check for round numbers that might indicate fabrication
        round_numbers = re.findall(r'\$[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|M|B))', output_text)
        if len(round_numbers) > 5:
            # Many round numbers might indicate estimates rather than real data
            issues.append(
                f"Many round financial figures ({len(round_numbers)}) — may indicate estimates"
            )
            # Don't penalize heavily — estimates are valid in research
            score -= 0.05

        return EvaluationResult(
            score=max(0.0, score),
            passed=score >= self.min_score,
            issues=issues,
            metrics={
                "hallucination_score": score,
                "uncertainty_phrases_found": len([
                    p for p in uncertainty_phrases
                    if re.search(p, output_text, re.IGNORECASE)
                ]),
            },
        )


def evaluate_workflow_outputs(
    manifest: dict,
    storage,
    run_prefix: str,
    min_score: float = 0.6,
) -> dict:
    """
    Evaluate all completed steps in a workflow manifest.

    Returns a dict mapping step index to EvaluationResult.
    """
    evaluator = OutputEvaluator(min_score=min_score)
    results = {}

    for step in manifest.get("steps", []):
        if step.get("status") != "complete":
            continue

        step_idx = step["step"]
        output_prefix = f"{run_prefix}/step_{step_idx}/output"
        output_keys = storage.list_keys(output_prefix)
        output_files = [k.split("/")[-1] for k in output_keys]

        # Read output text (from the context summary)
        context_key = f"{run_prefix}/context.json"
        output_text = ""
        if storage.key_exists(context_key):
            ctx = storage.read_json(context_key)
            step_ctx = ctx.get(f"step_{step_idx}", {})
            output_text = step_ctx.get("summary", "")

        result = evaluator.evaluate(
            instruction=step.get("instruction", ""),
            output_text=output_text,
            output_files=output_files,
        )

        results[step_idx] = {
            "score": result.score,
            "passed": result.passed,
            "issues": result.issues,
            "metrics": result.metrics,
        }

    return results
