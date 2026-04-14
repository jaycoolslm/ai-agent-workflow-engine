"""
OpenHarness runtime backend.

Uses the @openharness/core Agent SDK (TypeScript) to execute agent tasks.
Bridges Python entrypoint -> Node.js subprocess running the OpenHarness agent.

This runtime is LLM-agnostic: configure the model via LLM_MODEL and
OPENHARNESS_PROVIDER environment variables.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path


class OpenHarnessRuntime:
    """
    Runtime backend that delegates agent execution to OpenHarness (TypeScript).

    The agent is executed via a Node.js subprocess that uses @openharness/core
    to create an Agent with filesystem and bash tools, run the prompt, and
    stream output back.
    """

    def __init__(self, model: str = "gpt-4o", provider: str = "openai", **kwargs):
        self.model = model
        self.provider = provider

    async def execute(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        *,
        max_turns: int = 30,
    ) -> str:
        # Build the Node.js runner script
        runner_script = self._build_runner_script(
            prompt=prompt,
            skills_dir=skills_dir,
            output_dir=output_dir,
            max_turns=max_turns,
        )

        # Write the script to a temp file
        script_path = output_dir / "_openharness_runner.mjs"
        script_path.write_text(runner_script, encoding="utf-8")

        print(f"\n--- OpenHarness Agent Config ---")
        print(f"  Runtime:    openharness")
        print(f"  Provider:   {self.provider}")
        print(f"  Model:      {self.model}")
        print(f"  Skills dir: {skills_dir}")
        print(f"  Working dir: {output_dir}")
        print(f"  Max steps:  {max_turns}")
        print(f"--------------------------------\n")

        # Execute via Node.js
        proc = await asyncio.create_subprocess_exec(
            "node", str(script_path),
            cwd=str(output_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )

        collected = []
        # Stream stdout
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            collected.append(text)
            print(text, flush=True)

        await proc.wait()

        stderr_output = (await proc.stderr.read()).decode("utf-8", errors="replace")
        if proc.returncode != 0:
            error_msg = f"OpenHarness agent exited with code {proc.returncode}"
            if stderr_output:
                error_msg += f"\nStderr: {stderr_output[:2000]}"
            raise RuntimeError(error_msg)

        if stderr_output:
            print(f"  [STDERR] {stderr_output[:500]}", flush=True)

        # Clean up runner script
        try:
            script_path.unlink()
        except OSError:
            pass

        return "\n".join(collected)

    def _build_runner_script(
        self,
        prompt: str,
        skills_dir: Path | None,
        output_dir: Path,
        max_turns: int,
    ) -> str:
        """Generate the Node.js script that runs the OpenHarness agent."""
        # Escape prompt for JS template literal
        escaped_prompt = prompt.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

        # Build skills instruction if available
        skills_instruction = ""
        if skills_dir and skills_dir.exists():
            for skill_path in skills_dir.iterdir():
                skill_md = skill_path / "SKILL.md"
                if skill_path.is_dir() and skill_md.exists():
                    content = skill_md.read_text(encoding="utf-8")
                    escaped = content.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
                    skills_instruction += f"\n\n## Skill: {skill_path.name}\n{escaped}"

        escaped_skills = skills_instruction.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${") if skills_instruction else ""

        # Determine provider import
        provider_import, model_init = self._get_provider_config()

        return f"""
import {{ Agent, createFsTools, createBashTool, NodeFsProvider, NodeShellProvider }} from "@openharness/core";
{provider_import}

const fsTools = createFsTools(new NodeFsProvider());
const {{ bash }} = createBashTool(new NodeShellProvider());

const systemPrompt = `You are a workflow agent executing a step in a multi-agent pipeline.
Follow the instructions precisely. Write all output files to the specified output directory.
Be thorough and produce high-quality, structured output.{escaped_skills}`;

const agent = new Agent({{
  name: "workflow-agent",
  model: {model_init},
  systemPrompt,
  tools: {{ ...fsTools, bash }},
  maxSteps: {max_turns},
}});

const prompt = `{escaped_prompt}`;

let messages = [];
for await (const event of agent.run(messages, prompt)) {{
  switch (event.type) {{
    case "text.delta":
      process.stdout.write(event.text);
      break;
    case "tool.start":
      console.log(`\\n  [TOOL] ${{event.toolName}}...`);
      break;
    case "tool.done":
      console.log(`  [TOOL] ${{event.toolName}} done`);
      break;
    case "done":
      console.log(`\\n  [RESULT] result=${{event.result}}`);
      if (event.totalUsage) {{
        console.log(`  [RESULT] tokens=${{event.totalUsage.totalTokens || 0}}`);
      }}
      break;
    case "error":
      console.error(`  [ERROR] ${{event.error?.message || event.error}}`);
      break;
  }}
}}

await agent.close();
"""

    def _get_provider_config(self) -> tuple[str, str]:
        """Return the import statement and model initializer for the configured provider."""
        providers = {
            "openai": (
                'import { openai } from "@ai-sdk/openai";',
                f'openai("{self.model}")',
            ),
            "anthropic": (
                'import { anthropic } from "@ai-sdk/anthropic";',
                f'anthropic("{self.model}")',
            ),
            "google": (
                'import { google } from "@ai-sdk/google";',
                f'google("{self.model}")',
            ),
            "mistral": (
                'import { mistral } from "@ai-sdk/mistral";',
                f'mistral("{self.model}")',
            ),
        }

        if self.provider in providers:
            return providers[self.provider]

        # Default: OpenAI-compatible with custom base URL
        return (
            'import { createOpenAI } from "@ai-sdk/openai";',
            f'createOpenAI({{ baseURL: process.env.OPENAI_BASE_URL || "https://api.openai.com/v1" }})("{self.model}")',
        )
