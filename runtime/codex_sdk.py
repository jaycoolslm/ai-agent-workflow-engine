"""
OpenAI Codex CLI SDK runtime backend.

Uses the openai-agents Python package (pip install openai-agents) which
runs the Codex CLI as an MCP (Model Context Protocol) server. The agent
gets access to Codex tools (start_conversation, continue_conversation)
for sandboxed code execution.

Requirements:
    pip install openai-agents
    npx codex (or npm install -g @openai/codex)

Environment:
    OPENAI_API_KEY  — Required for OpenAI model access.

See: https://developers.openai.com/codex/guides/agents-sdk
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class CodexSDKRuntime:
    """
    Runtime backend using the OpenAI Agents SDK + Codex MCP server.

    Launches Codex CLI as an MCP server process, then uses the Agents SDK
    to orchestrate tool calls (file I/O, bash, code execution) within the
    Codex sandboxed environment.
    """

    def __init__(self, *, model: str = "", **kwargs):
        self.model = model or os.environ.get("CODEX_MODEL", "gpt-4.1")

    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        try:
            from agents import Agent, Runner
            from agents.mcp import MCPServerStdio
        except ImportError:
            raise RuntimeError(
                "openai-agents package is not installed. "
                "Install with: pip install openai-agents"
            )

        # Build the full prompt with skills injected
        full_prompt = self._build_prompt(prompt, skills_dir, output_dir)

        print(f"\n--- Codex Agent Config ---")
        print(f"  Runtime:    codex (MCP server)")
        print(f"  Model:      {self.model}")
        print(f"  Skills dir: {skills_dir}")
        print(f"  Working dir: {output_dir}")
        print(f"  Max turns:  {max_turns}")
        print(f"--------------------------\n")

        # Launch Codex CLI as an MCP server and run the agent
        async with MCPServerStdio(
            name="Codex CLI",
            params={
                "command": "npx",
                "args": ["-y", "codex", "mcp-server"],
            },
            client_session_timeout_seconds=360000,
        ) as codex_mcp_server:
            print("  [INIT] Codex MCP server started")

            # List available tools for logging
            tools = await codex_mcp_server.list_tools()
            tool_names = [t.name for t in tools]
            print(f"  [TOOLS] Available: {', '.join(tool_names)}")

            # Create the agent with Codex tools
            agent = Agent(
                name="workflow-agent",
                instructions=(
                    f"You are a workflow agent. Work in directory: {output_dir}\n"
                    f"Write all output files to that directory.\n\n"
                    f"{full_prompt}"
                ),
                mcp_servers=[codex_mcp_server],
                model=self.model,
            )

            print(f"  [AGENT] Created with model={self.model}")

            # Run the agent
            result = await Runner.run(
                agent,
                input=full_prompt,
                max_turns=max_turns,
            )

            # Extract the final output
            final_output = result.final_output if hasattr(result, "final_output") else ""

            # Log tool usage from the run
            if hasattr(result, "raw_responses"):
                for resp in result.raw_responses:
                    if hasattr(resp, "output"):
                        for item in resp.output:
                            self._log_item(item)

        print(f"\n  [RESULT] model={self.model}")
        print(f"  [RESULT] output_length={len(final_output)}")

        return final_output

    def _build_prompt(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
    ) -> str:
        """Build full prompt with skills injected as system context."""
        parts = [prompt]

        if skills_dir and skills_dir.exists():
            skills_text = []
            for skill_path in sorted(skills_dir.iterdir()):
                skill_md = skill_path / "SKILL.md"
                if skill_path.is_dir() and skill_md.exists():
                    content = skill_md.read_text(encoding="utf-8")
                    skills_text.append(f"\n## Skill: {skill_path.name}\n{content}")
                    print(f"  [SKILL] Loaded: {skill_path.name}")

            if skills_text:
                parts.insert(0, "## Agent Skills\n" + "\n".join(skills_text) + "\n")

        return "\n".join(parts)

    @staticmethod
    def _log_item(item) -> None:
        """Log a response item for observability."""
        item_type = getattr(item, "type", "")
        if item_type == "tool_use":
            name = getattr(item, "name", "unknown")
            print(f"  [TOOL] {name}", flush=True)
        elif item_type == "message":
            text = getattr(item, "text", "")
            if text:
                preview = text[:150].replace("\n", " ")
                print(f"  [MSG] {preview}", flush=True)
