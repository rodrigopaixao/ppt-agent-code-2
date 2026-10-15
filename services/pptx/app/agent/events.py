"""Turn Agent SDK messages into short activity lines."""

import re
from typing import List


def redact(value: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[redacted]", value)


def describe_message(message) -> List[str]:
    lines: List[str] = []
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            name = getattr(block, "name", None)
            text = getattr(block, "text", None)
            if name:
                lines.append(f"Using {name}")
            elif isinstance(text, str) and text.strip():
                lines.append(redact(text.strip().splitlines()[0])[:180])
    if getattr(message, "subtype", None) == "success" and getattr(message, "result", None):
        lines.append(redact(str(message.result).strip().splitlines()[0])[:180])
    if getattr(message, "is_error", False):
        errors = getattr(message, "errors", None) or []
        lines.append(redact("; ".join(str(error) for error in errors) or "The agent run failed.")[:180])
    return [line for line in lines if line]
