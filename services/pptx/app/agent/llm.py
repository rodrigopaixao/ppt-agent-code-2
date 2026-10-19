"""Call Gemini through OpenRouter's chat completions API. Conversations are kept in the workspace so revisions can continue them."""

import asyncio
import base64
import json
import re
import uuid
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import httpx

MAX_OUTPUT_TOKENS = 32768
TIMEOUT_SECONDS = 600
RETRY_ATTEMPTS = 6
RETRY_DELAY = 2.0
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
SESSION_ID = re.compile(r"[0-9a-f]{32}")
TRANSPORT: Optional[httpx.AsyncBaseTransport] = None


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


def has_session(workspace: Path, session_id: Optional[str]) -> bool:
    return bool(session_id) and SESSION_ID.fullmatch(session_id or "") is not None and _session_path(workspace, session_id).exists()


def _session_path(workspace: Path, session_id: str) -> Path:
    return workspace / "sessions" / f"{session_id}.json"


async def ask(
    workspace: Path,
    request: dict,
    system: str,
    prompt: str,
    *,
    resume: Optional[str] = None,
    images: Sequence[Tuple[str, Path]] = (),
) -> Tuple[str, str]:
    """Send one message and return (reply text, session id).

    Text-only calls continue the conversation in ``resume`` (or start one). Calls with images are one-off.
    """
    if not request.get("api_key") or request["api_key"] == "<API_KEY>":
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env.")
    if not request.get("model"):
        raise RuntimeError("OPENROUTER_MODEL is not set in .env.")
    session_id = resume if has_session(workspace, resume) else ("" if images else uuid.uuid4().hex)
    history: List[dict] = []
    if session_id and has_session(workspace, session_id):
        history = json.loads(_session_path(workspace, session_id).read_text(encoding="utf-8"))

    content: List[dict] = [{"type": "text", "text": prompt}]
    for label, image in images:
        encoded = base64.b64encode(image.read_bytes()).decode("ascii")
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}})
    messages = [{"role": "system", "content": system}]
    messages += [{"role": turn["role"], "content": turn["text"]} for turn in history]
    messages.append({"role": "user", "content": content if images else prompt})

    reply = await _post(
        request,
        {
            "model": request["model"],
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": MAX_OUTPUT_TOKENS,
        },
    )
    choice = (reply.get("choices") or [{}])[0]
    text = str((choice.get("message") or {}).get("content") or "")
    if not text:
        raise RuntimeError(f"The model returned no text (finish reason: {choice.get('finish_reason') or 'unknown'}).")

    if session_id:
        history += [{"role": "user", "text": prompt}, {"role": "assistant", "text": text}]
        path = _session_path(workspace, session_id)
        path.parent.mkdir(exist_ok=True)
        scratch = path.with_suffix(".tmp")
        scratch.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        scratch.replace(path)
    return text, session_id


async def _post(request: dict, body: dict) -> dict:
    url = (request.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {request['api_key']}", "X-Title": "Deck Studio"}
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=TRANSPORT) as client:
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = await client.post(url, json=body, headers=headers)
            except httpx.TransportError as error:
                if attempt == RETRY_ATTEMPTS:
                    raise RuntimeError(f"Could not reach OpenRouter: {error}") from error
                await asyncio.sleep(RETRY_DELAY * 2 ** (attempt - 1))
                continue
            if response.status_code in RETRY_STATUS and attempt < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY * 2 ** (attempt - 1))
                continue
            payload = _json(response)
            error = payload.get("error")
            if response.status_code >= 400 or error:
                message = error.get("message") if isinstance(error, dict) else response.text[:300]
                raise RuntimeError(f"OpenRouter returned {response.status_code}: {message}")
            return payload
    raise RuntimeError("OpenRouter did not respond.")


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
