"""
Runtime factory — returns the right AgentRuntime backend based on a string key.

Mirrors storage/factory.py: lazy imports, single entry point, fail-fast on unknown.
"""

from __future__ import annotations

from runtime.protocol import AgentRuntimeProtocol


def get_runtime(backend: str, **kwargs) -> AgentRuntimeProtocol:
    """
    Create a runtime backend instance.

    Args:
        backend: One of "claude", "deepagent", "codex".
        **kwargs: Backend-specific config passed to the constructor.
            claude:    (none — reads ANTHROPIC_API_KEY from env)
            deepagent: model (str, LangChain provider:model format)
            codex:     (stub — raises NotImplementedError)
    """
    if backend == "claude":
        from runtime.claude_sdk import ClaudeSDKRuntime

        return ClaudeSDKRuntime(**kwargs)

    if backend == "deepagent":
        from runtime.deep_agents import DeepAgentsRuntime

        return DeepAgentsRuntime(**kwargs)

    if backend == "codex":
        from runtime.codex_sdk import CodexSDKRuntime

        return CodexSDKRuntime(**kwargs)

    supported = ", ".join(["claude", "deepagent", "codex"])
    raise ValueError(
        f"Unknown runtime backend: '{backend}'. Supported: {supported}"
    )
