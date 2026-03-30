"""
LangChain Deep Agents runtime backend.

LLM-agnostic coding agent runtime. Model is configurable via LLM_MODEL env var
using LangChain's provider:model format (e.g. "openai:gpt-5", "anthropic:claude-sonnet-4-6").

Skills are loaded via SKILL.md: passed to create_deep_agent(skills=[...])
which wires up SkillsMiddleware for automatic discovery and system prompt injection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class DeepAgentsRuntime:
    def __init__(self, *, model: str = "", **kwargs):
        self.model = (
            model
            or os.environ.get("LLM_MODEL", "")
            or "anthropic:claude-sonnet-4-6"
        )

    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        from deepagents import create_deep_agent
        from deepagents.backends import FilesystemBackend

        backend = FilesystemBackend(root_dir=str(output_dir))

        # Symlink skills into the workspace so the backend can read them.
        # SkillsMiddleware reads through the backend (relative to root_dir),
        # so skills must be inside the output_dir tree.
        skills = None
        if skills_dir and skills_dir.exists():
            workspace_skills = output_dir / "skills"
            workspace_skills.mkdir(parents=True, exist_ok=True)
            for skill in skills_dir.iterdir():
                if skill.is_dir() and (skill / "SKILL.md").exists():
                    target = workspace_skills / skill.name
                    if not target.exists():
                        os.symlink(skill, target)
                        print(f"  [SKILL] Linked: {skill.name}")
            skills = ["./skills/"]

        print(f"\n--- Agent Config ---")
        print(f"  Runtime:    deepagent")
        print(f"  Model:      {self.model}")
        print(f"  Skills dir: {skills_dir}")
        print(f"  Working dir: {output_dir}")
        print(f"  Max turns:  {max_turns}")
        print(f"--------------------\n")

        agent = create_deep_agent(
            model=self.model,
            skills=skills,
            backend=backend,
        )

        # Stream events for real-time logging (matches Claude SDK observability)
        collected = []
        tool_count = 0
        config = {"recursion_limit": max_turns * 2}

        async for event in agent.astream_events(
            {"messages": [("human", prompt)]},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")

            # --- LLM text output streaming ---
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    content = chunk.content
                    if isinstance(content, str):
                        print(content, end="", flush=True)

            # --- Tool invocations ---
            elif kind == "on_tool_start":
                tool_count += 1
                name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                self._log_tool_start(name, tool_input)

            elif kind == "on_tool_end":
                name = event.get("name", "unknown")
                output = event.get("data", {}).get("output", "")
                if isinstance(output, str) and len(output) > 200:
                    output = output[:200] + "..."
                print(f"  [TOOL DONE] {name}", flush=True)

            # --- Final AI message ---
            elif kind == "on_chat_model_end":
                output = event.get("data", {}).get("output")
                if output and hasattr(output, "content"):
                    content = output.content
                    if isinstance(content, str) and content:
                        collected.append(content)
                        print(flush=True)  # newline after streamed text

        result_text = "\n".join(collected)

        # Log result summary
        print(f"\n  [RESULT] model={self.model}")
        print(f"  [RESULT] tool_calls={tool_count}")

        return result_text

    @staticmethod
    def _extract_path(tool_input) -> str:
        """Extract file path from tool input, trying common key names."""
        if not isinstance(tool_input, dict):
            return str(tool_input)[:150]
        for key in ("file_path", "path", "filename", "file", "file_name"):
            if key in tool_input:
                return str(tool_input[key])
        return ""

    @staticmethod
    def _log_tool_start(name: str, tool_input) -> None:
        """Log a tool invocation for observability."""
        if isinstance(tool_input, dict):
            input_str = json.dumps(tool_input)
        else:
            input_str = str(tool_input)

        if name in ("execute", "shell", "bash"):
            cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else str(tool_input)
            print(f"  [BASH] {str(cmd)[:150]}", flush=True)
        elif name == "read_file":
            path = DeepAgentsRuntime._extract_path(tool_input)
            tag = "SKILL READ" if "SKILL.md" in path else "READ"
            print(f"  [{tag}] {path}", flush=True)
        elif name == "write_file":
            path = DeepAgentsRuntime._extract_path(tool_input)
            print(f"  [WRITE] {path}", flush=True)
        elif name == "edit_file":
            path = DeepAgentsRuntime._extract_path(tool_input)
            print(f"  [EDIT] {path}", flush=True)
        elif name in ("ls", "glob"):
            print(f"  [GLOB] {input_str[:150]}", flush=True)
        elif name == "grep":
            print(f"  [GREP] {input_str[:150]}", flush=True)
        elif name == "write_todos":
            print(f"  [PLAN] {input_str[:200]}", flush=True)
        elif name == "task":
            print(f"  [SUBAGENT] {input_str[:200]}", flush=True)
        else:
            print(f"  [TOOL] {name}: {input_str[:200]}", flush=True)
