"""
Claude Agent SDK runtime backend.

Extracted from entrypoint.py — preserves all existing behavior:
bypassPermissions, tool logging, streaming message handling.

Skills are loaded via SKILL.md: symlinked into {cwd}/.claude/skills/
so the SDK discovers them with setting_sources=["project"].
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class ClaudeSDKRuntime:
    def __init__(self, **kwargs):
        # No config needed — Claude SDK reads ANTHROPIC_API_KEY from env.
        pass

    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            ResultMessage,
            SystemMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )

        # Set up .claude/skills/ in the workspace so the SDK discovers them
        self._link_skills(skills_dir, output_dir)

        print(f"\n--- Agent Config ---")
        print(f"  Runtime:    claude")
        print(f"  Skills dir: {skills_dir}")
        print(f"  Working dir: {output_dir}")
        print(f"  Permission mode: bypassPermissions")
        print(f"  Disallowed tools: ComputerUse, NotebookEdit")
        print(f"  Max turns: {max_turns}")
        print(f"--------------------\n")

        collected = []

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                permission_mode="bypassPermissions",
                disallowed_tools=["ComputerUse", "NotebookEdit"],
                setting_sources=["project"],
                cwd=str(output_dir),
                max_turns=max_turns,
            ),
        ):
            # --- System messages (init, skill loading, etc) ---
            if isinstance(message, SystemMessage):
                if message.subtype == "init":
                    plugins = message.data.get("plugins", [])
                    commands = message.data.get("slash_commands", [])
                    print(f"  [INIT] Plugins loaded: {len(plugins)}")
                    for p in plugins:
                        print(
                            f"         - {p.get('name', 'unknown')} ({p.get('path', '')})"
                        )
                    print(f"  [INIT] Slash commands: {len(commands)}")
                    for cmd in commands:
                        if ":" in str(cmd):
                            print(f"         - {cmd}")
                else:
                    print(
                        f"  [SYSTEM:{message.subtype}] "
                        f"{json.dumps(message.data, default=str)[:200]}"
                    )

            # --- Assistant messages (text, tool calls) ---
            elif isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        collected.append(block.text)
                        print(block.text, flush=True)
                    elif isinstance(block, ToolUseBlock):
                        self._log_tool_call(block)

            # --- Result message (final) ---
            elif isinstance(message, ResultMessage):
                print(f"\n  [RESULT] subtype={message.subtype}")
                print(f"  [RESULT] turns={message.num_turns}")
                print(f"  [RESULT] duration={message.duration_ms}ms")
                if message.total_cost_usd is not None:
                    print(f"  [RESULT] cost=${message.total_cost_usd:.4f}")
                if message.usage:
                    print(
                        f"  [RESULT] tokens in={message.usage.get('input_tokens', 0)} "
                        f"out={message.usage.get('output_tokens', 0)}"
                    )

        return "\n".join(collected)

    @staticmethod
    def _link_skills(skills_dir: Path | None, output_dir: Path) -> None:
        """Symlink SKILL.md directories into {output_dir}/.claude/skills/."""
        workspace_skills = output_dir / ".claude" / "skills"
        workspace_skills.mkdir(parents=True, exist_ok=True)

        if not skills_dir or not skills_dir.exists():
            return

        for skill in skills_dir.iterdir():
            if skill.is_dir() and (skill / "SKILL.md").exists():
                target = workspace_skills / skill.name
                if not target.exists():
                    os.symlink(skill, target)
                    print(f"  [SKILL] Linked: {skill.name}")

    @staticmethod
    def _log_tool_call(block) -> None:
        """Log a tool call for observability."""
        if block.name == "Skill":
            print(
                f"  [SKILL CALL] {json.dumps(block.input)[:300]}",
                flush=True,
            )
        elif block.name == "Bash":
            print(
                f"  [BASH] {block.input.get('command', '')[:150]}",
                flush=True,
            )
        elif block.name in ("Read", "Write", "Edit"):
            print(
                f"  [{block.name.upper()}] {block.input.get('file_path', '')}",
                flush=True,
            )
        elif block.name in ("WebSearch", "WebFetch"):
            print(
                f"  [{block.name.upper()}] "
                f"{block.input.get('query', block.input.get('url', ''))[:150]}",
                flush=True,
            )
        else:
            print(
                f"  [TOOL] {block.name}: {json.dumps(block.input)[:200]}",
                flush=True,
            )
