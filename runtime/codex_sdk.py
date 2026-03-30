"""
OpenAI Codex SDK runtime backend — stub.

Codex SDK is TypeScript-only (@openai/codex-sdk). A Python implementation
would need to either wrap the TypeScript SDK via subprocess or use the
OpenAI Agents SDK with ShellTool + ApplyPatchTool as a Python-native alternative.

See: https://developers.openai.com/codex/sdk
"""

from __future__ import annotations

from pathlib import Path


class CodexSDKRuntime:
    def __init__(self, **kwargs):
        pass

    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        raise NotImplementedError(
            "Codex SDK backend not yet implemented. "
            "Requires @openai/codex-sdk (TypeScript). "
            "See: https://developers.openai.com/codex/sdk"
        )
