"""
AgentRuntimeProtocol — contract all runtime backends must satisfy.

Mirrors the storage/protocol.py pattern: a @runtime_checkable Protocol
that any backend can implement via structural subtyping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentRuntimeProtocol(Protocol):
    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        """
        Run an agent with the given prompt and skills.

        Args:
            prompt:     Fully-formed task prompt (instruction + context + file list).
            skills_dir: Directory containing SKILL.md subdirectories for this step,
                        or None if no skills are needed.
            output_dir: Working directory for the agent (reads inputs, writes outputs).
            max_turns:  Maximum agent loop iterations.

        Returns:
            Collected text output from the agent.
        """
        ...
