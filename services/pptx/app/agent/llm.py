"""Call the model through the Claude Agent SDK, routed to the configured provider."""

import json
import os
import re
from pathlib import Path
from typing import Optional, Tuple


def json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    raw = fenced.group(1) if fenced else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def ask(
    workspace: Path,
    request: dict,
    system: str,
    prompt: str,
    *,
    resume: Optional[str] = None,
    read_files: bool = False,
    max_turns: int = 4,
    budget: float = 2.0,
) -> Tuple[str, str]:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    environment = os.environ.copy()
    environment["PATH"] = "/opt/homebrew/bin:" + environment.get("PATH", "")
    environment["ANTHROPIC_BASE_URL"] = request["base_url"]
    environment["ANTHROPIC_AUTH_TOKEN"] = request["api_key"]
    environment["ANTHROPIC_API_KEY"] = ""
    environment["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "32000"
    for name in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
    ):
        environment[name] = request["model"]
    tools = ["Read"] if read_files else []
    blocked = ["WebFetch", "WebSearch", "WebBrowser", "Task", "Bash", "Write", "Edit", "Glob", "Grep"]
    if not read_files:
        blocked.append("Read")
    options = ClaudeAgentOptions(
        cwd=workspace,
        system_prompt=system,
        tools=tools,
        allowed_tools=tools,
        disallowed_tools=blocked,
        permission_mode="bypassPermissions",
        setting_sources=[],
        model=request["model"],
        max_turns=max_turns,
        max_budget_usd=budget,
        resume=resume or None,
        env=environment,
        extra_args={
            "allow-dangerously-skip-permissions": None,
            "dangerously-skip-permissions": None,
        },
        stderr=lambda line: None,
    )
    result = ""
    session_id = resume or ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            session_id = message.session_id or session_id
            if message.result:
                result = message.result
    return result, session_id
