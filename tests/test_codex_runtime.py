"""
Tests for the Codex CLI SDK runtime backend.

Validates the CodexSDKRuntime class without requiring an OpenAI API key.
Uses mocking to simulate the openai-agents SDK + Codex MCP server behavior.

Run with:
    python test_codex_runtime.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))


def _passed(name):
    print(f"  PASS  {name}")


def _failed(name, detail=""):
    print(f"  FAIL  {name}")
    if detail:
        print(f"        {detail}")
    sys.exit(1)


# ------------------------------------------------------------------
# Test 1: Import and instantiation
# ------------------------------------------------------------------
def test_import():
    print("[1] Import and instantiation")
    from runtime.codex_sdk import CodexSDKRuntime

    # Default model
    rt = CodexSDKRuntime()
    assert rt.model == "gpt-4.1", f"Expected gpt-4.1, got {rt.model}"
    _passed("Default model is gpt-4.1")

    # Custom model
    rt2 = CodexSDKRuntime(model="gpt-5.4")
    assert rt2.model == "gpt-5.4", f"Expected gpt-5.4, got {rt2.model}"
    _passed("Custom model accepted")

    # Env var model
    os.environ["CODEX_MODEL"] = "o3-mini"
    rt3 = CodexSDKRuntime()
    assert rt3.model == "o3-mini", f"Expected o3-mini, got {rt3.model}"
    del os.environ["CODEX_MODEL"]
    _passed("CODEX_MODEL env var respected")


# ------------------------------------------------------------------
# Test 2: Protocol conformance
# ------------------------------------------------------------------
def test_protocol():
    print("\n[2] Protocol conformance")
    from runtime.codex_sdk import CodexSDKRuntime
    from runtime.protocol import AgentRuntimeProtocol

    rt = CodexSDKRuntime()
    assert isinstance(rt, AgentRuntimeProtocol), "Must satisfy AgentRuntimeProtocol"
    _passed("Satisfies AgentRuntimeProtocol")


# ------------------------------------------------------------------
# Test 3: Factory integration
# ------------------------------------------------------------------
def test_factory():
    print("\n[3] Factory integration")
    from runtime.factory import get_runtime
    from runtime.codex_sdk import CodexSDKRuntime

    rt = get_runtime("codex", model="gpt-4.1")
    assert isinstance(rt, CodexSDKRuntime)
    assert rt.model == "gpt-4.1"
    _passed("get_runtime('codex') returns CodexSDKRuntime")


# ------------------------------------------------------------------
# Test 4: Prompt building with skills
# ------------------------------------------------------------------
def test_prompt_building():
    print("\n[4] Prompt building with skills")
    from runtime.codex_sdk import CodexSDKRuntime

    rt = CodexSDKRuntime()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Test without skills
        result = rt._build_prompt("Do X", None, output_dir)
        assert "Do X" in result
        _passed("Prompt without skills")

        # Test with skills
        skills_dir = Path(tmpdir) / "skills"
        skill1 = skills_dir / "research"
        skill1.mkdir(parents=True)
        (skill1 / "SKILL.md").write_text("---\nname: research\n---\nDo research things")

        skill2 = skills_dir / "audit"
        skill2.mkdir(parents=True)
        (skill2 / "SKILL.md").write_text("---\nname: audit\n---\nDo audit things")

        result = rt._build_prompt("Do Y", skills_dir, output_dir)
        assert "Do Y" in result
        assert "Agent Skills" in result
        assert "research" in result
        assert "audit" in result
        _passed("Prompt with skills injected")


# ------------------------------------------------------------------
# Test 5: Item logging
# ------------------------------------------------------------------
def test_item_logging():
    print("\n[5] Item logging")
    from runtime.codex_sdk import CodexSDKRuntime
    import io
    from contextlib import redirect_stdout

    # Test tool_use item
    item = MagicMock()
    item.type = "tool_use"
    item.name = "write_file"
    f = io.StringIO()
    with redirect_stdout(f):
        CodexSDKRuntime._log_item(item)
    assert "TOOL" in f.getvalue()
    assert "write_file" in f.getvalue()
    _passed("Tool use item logged")

    # Test message item
    item = MagicMock()
    item.type = "message"
    item.text = "Hello from Codex agent"
    f = io.StringIO()
    with redirect_stdout(f):
        CodexSDKRuntime._log_item(item)
    assert "MSG" in f.getvalue()
    assert "Hello" in f.getvalue()
    _passed("Message item logged")

    # Test unknown item type (should not crash)
    item = MagicMock()
    item.type = "unknown"
    f = io.StringIO()
    with redirect_stdout(f):
        CodexSDKRuntime._log_item(item)
    # Should not crash, may produce no output
    _passed("Unknown item type handled safely")


# ------------------------------------------------------------------
# Test 6: Mocked execution (full async flow with openai-agents)
# ------------------------------------------------------------------
def test_mocked_execution():
    print("\n[6] Mocked async execution (openai-agents + MCP)")
    from runtime.codex_sdk import CodexSDKRuntime

    rt = CodexSDKRuntime(model="gpt-4.1")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Mock the Runner.run result
        mock_run_result = MagicMock()
        mock_run_result.final_output = "Task completed successfully via MCP"

        # Mock MCPServerStdio context manager
        mock_mcp_server = AsyncMock()
        mock_tool = MagicMock()
        mock_tool.name = "codex_start_conversation"
        mock_mcp_server.list_tools = AsyncMock(return_value=[mock_tool])

        mock_mcp_cls = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_mcp_instance.__aenter__ = AsyncMock(return_value=mock_mcp_server)
        mock_mcp_instance.__aexit__ = AsyncMock(return_value=False)
        mock_mcp_cls.return_value = mock_mcp_instance

        # Mock Runner
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_run_result)

        # Mock Agent class
        mock_agent_cls = MagicMock()

        with patch.dict("sys.modules", {
            "agents": MagicMock(
                Agent=mock_agent_cls,
                Runner=mock_runner,
            ),
            "agents.mcp": MagicMock(
                MCPServerStdio=mock_mcp_cls,
            ),
        }):
            result = asyncio.run(rt.execute(
                prompt="Write a hello world",
                skills_dir=None,
                output_dir=output_dir,
            ))

        assert "Task completed successfully via MCP" in result
        _passed("Mocked execution returned correct result")


# ------------------------------------------------------------------
# Test 7: Entrypoint integration
# ------------------------------------------------------------------
def test_entrypoint():
    print("\n[7] Entrypoint integration")

    # Test that entrypoint creates codex runtime
    os.environ["AGENT_RUNTIME"] = "codex"
    os.environ["CODEX_MODEL"] = "gpt-4.1"
    os.environ["OPENAI_API_KEY"] = "test-key"
    os.environ["BUCKET"] = "test"
    os.environ["RUN_PREFIX"] = "test"
    os.environ["PLUGIN_NAME"] = "test"

    # Import fresh
    import importlib
    import entrypoint
    importlib.reload(entrypoint)

    # Verify _create_runtime returns CodexSDKRuntime when AGENT_RUNTIME=codex
    from runtime.codex_sdk import CodexSDKRuntime
    entrypoint.AGENT_RUNTIME = "codex"
    rt = entrypoint._create_runtime()
    assert isinstance(rt, CodexSDKRuntime), f"Expected CodexSDKRuntime, got {type(rt)}"
    _passed("Entrypoint creates CodexSDKRuntime for AGENT_RUNTIME=codex")

    # Cleanup
    for key in ["AGENT_RUNTIME", "CODEX_MODEL", "OPENAI_API_KEY", "BUCKET", "RUN_PREFIX", "PLUGIN_NAME"]:
        os.environ.pop(key, None)


# ------------------------------------------------------------------
# Test 8: Router codex validation
# ------------------------------------------------------------------
def test_router_codex_env():
    print("\n[8] Router Codex env var support")

    # Verify the router has OPENAI_API_KEY reference
    with open("router.py", "r") as f:
        content = f.read()

    assert "OPENAI_API_KEY" in content, "Router should reference OPENAI_API_KEY"
    assert 'AGENT_RUNTIME == "codex"' in content, "Router should check for codex runtime"
    _passed("Router has Codex runtime support")


def main():
    print("=" * 60)
    print("CODEX CLI SDK RUNTIME TESTS (no API key needed)")
    print("=" * 60)
    print()

    test_import()
    test_protocol()
    test_factory()
    test_prompt_building()
    test_item_logging()
    test_mocked_execution()
    test_entrypoint()
    test_router_codex_env()

    print()
    print("=" * 60)
    print("ALL 8 TESTS PASSED")
    print("=" * 60)
    print()
    print("The Codex CLI SDK runtime is fully wired up.")
    print("To run with real API:")
    print("  export OPENAI_API_KEY=sk-...")
    print("  export AGENT_RUNTIME=codex")
    print("  python router.py --bucket workflows --run-prefix runs/run_001 --seed")


if __name__ == "__main__":
    main()
