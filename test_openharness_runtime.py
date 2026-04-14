"""
Test: validates the OpenHarness runtime integration.

Tests:
  1. OpenHarness runtime factory registration
  2. Runner script generation
  3. Provider configuration (openai, anthropic, google, mistral)
  4. Skills injection into system prompt
  5. Script escaping (template literals, backticks)

Run with:
    python test_openharness_runtime.py
    # No API key needed — only tests script generation, not execution.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from runtime.openharness import OpenHarnessRuntime
from runtime.factory import get_runtime


def test_passed(name):
    print(f"  PASS  {name}")


def test_failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


def main():
    print("=" * 60)
    print("OPENHARNESS RUNTIME TEST (no API key needed)")
    print("=" * 60)
    print()

    # ------------------------------------------------------------------
    # Test 1: Factory registration
    # ------------------------------------------------------------------
    print("[1] Runtime factory registration")
    try:
        runtime = get_runtime("openharness", model="gpt-4o", provider="openai")
        assert isinstance(runtime, OpenHarnessRuntime)
        test_passed("OpenHarness runtime registered in factory")
    except Exception as e:
        test_failed("Factory registration", str(e))

    # ------------------------------------------------------------------
    # Test 2: Provider configs
    # ------------------------------------------------------------------
    print("\n[2] Provider configuration")
    providers = {
        "openai": ("@ai-sdk/openai", 'openai("gpt-4o")'),
        "anthropic": ("@ai-sdk/anthropic", 'anthropic("claude-sonnet-4-20250514")'),
        "google": ("@ai-sdk/google", 'google("gemini-pro")'),
        "mistral": ("@ai-sdk/mistral", 'mistral("mistral-large")'),
    }
    for provider_name, (expected_import, _) in providers.items():
        rt = OpenHarnessRuntime(model="test-model", provider=provider_name)
        imp, init = rt._get_provider_config()
        assert expected_import in imp, f"Expected {expected_import} in {imp}"
    test_passed(f"All {len(providers)} providers configured correctly")

    # ------------------------------------------------------------------
    # Test 3: Custom provider (OpenAI-compatible)
    # ------------------------------------------------------------------
    print("\n[3] Custom provider (OpenAI-compatible)")
    rt = OpenHarnessRuntime(model="my-model", provider="custom")
    imp, init = rt._get_provider_config()
    assert "createOpenAI" in imp
    assert "OPENAI_BASE_URL" in init
    test_passed("Custom provider uses createOpenAI with base URL")

    # ------------------------------------------------------------------
    # Test 4: Runner script generation
    # ------------------------------------------------------------------
    print("\n[4] Runner script generation")
    rt = OpenHarnessRuntime(model="gpt-4o", provider="openai")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        script = rt._build_runner_script(
            prompt="Research TestCorp and write a report",
            skills_dir=None,
            output_dir=output_dir,
            max_turns=20,
        )

        assert "Agent" in script
        assert "createFsTools" in script
        assert "createBashTool" in script
        assert "maxSteps: 20" in script
        assert "Research TestCorp" in script
        assert "@openharness/core" in script
        test_passed("Runner script contains all required elements")

    # ------------------------------------------------------------------
    # Test 5: Skills injection
    # ------------------------------------------------------------------
    print("\n[5] Skills injection into system prompt")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Create a fake skills directory
        skills_dir = Path(tmpdir) / "skills" / "test-skill"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            "# Test Skill\nYou can do X, Y, Z.",
            encoding="utf-8",
        )

        rt = OpenHarnessRuntime(model="gpt-4o", provider="openai")
        script = rt._build_runner_script(
            prompt="Do a task",
            skills_dir=skills_dir.parent,
            output_dir=output_dir,
            max_turns=10,
        )

        assert "Skill: test-skill" in script
        assert "You can do X, Y, Z" in script
        test_passed("Skills injected into system prompt")

    # ------------------------------------------------------------------
    # Test 6: Prompt escaping
    # ------------------------------------------------------------------
    print("\n[6] Prompt escaping for JS template literals")
    rt = OpenHarnessRuntime(model="gpt-4o", provider="openai")
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        tricky_prompt = "Use `backticks` and ${variables} and \\backslashes"
        script = rt._build_runner_script(
            prompt=tricky_prompt,
            skills_dir=None,
            output_dir=output_dir,
            max_turns=10,
        )

        # The backticks and ${} should be escaped
        assert "\\`backticks\\`" in script
        assert "\\${variables}" in script
        test_passed("Backticks and template expressions escaped correctly")

    # ------------------------------------------------------------------
    # Test 7: OpenHarness package.json exists
    # ------------------------------------------------------------------
    print("\n[7] OpenHarness package.json")
    pkg_path = Path(__file__).parent / "openharness" / "package.json"
    assert pkg_path.exists(), f"Missing {pkg_path}"
    import json
    pkg = json.loads(pkg_path.read_text())
    assert "@openharness/core" in pkg["dependencies"]
    assert pkg["type"] == "module"
    test_passed("package.json has @openharness/core dependency")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL 7 OPENHARNESS RUNTIME TESTS PASSED")
    print("=" * 60)
    print()
    print("What this proves:")
    print("  - OpenHarness runtime is registered in the factory")
    print("  - All 4 AI SDK providers configured (openai, anthropic, google, mistral)")
    print("  - Custom OpenAI-compatible providers supported")
    print("  - Runner script generation is correct")
    print("  - Skills are injected into system prompt")
    print("  - JS template literal escaping works")
    print()
    print("To run with a real API key:")
    print("  export OPENAI_API_KEY=sk-...")
    print("  AGENT_RUNTIME=openharness LLM_MODEL=gpt-4o python entrypoint.py")


if __name__ == "__main__":
    main()
