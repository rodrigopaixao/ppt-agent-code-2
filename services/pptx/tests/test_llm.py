import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.agent import llm
from app.agent.events import redact

REQUEST = {"api_key": "test-key", "model": "google/gemini-test", "base_url": "https://router.test/api/v1"}


class FakeRouter:
    def __init__(self, replies):
        self.replies = list(replies)
        self.bodies = []
        self.headers = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        self.headers.append(request.headers)
        assert str(request.url) == "https://router.test/api/v1/chat/completions"
        next_reply = self.replies.pop(0)
        if isinstance(next_reply, Exception):
            raise next_reply
        status, payload = next_reply
        return httpx.Response(status, json=payload)


def reply(text: str, finish: str = "stop"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch) -> FakeRouter:
    fake = FakeRouter([])
    monkeypatch.setattr(llm, "TRANSPORT", httpx.MockTransport(fake))
    monkeypatch.setattr(llm, "RETRY_DELAY", 0)
    return fake


def test_conversations_are_saved_and_resumed(tmp_path: Path, router: FakeRouter) -> None:
    router.replies = [reply('{"step": 1}'), reply('{"step": 2}')]
    first, session = asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write the deck"))
    second, resumed = asyncio.run(llm.ask(tmp_path, REQUEST, "system", "fix slide 2", resume=session))

    assert (first, second) == ('{"step": 1}', '{"step": 2}')
    assert resumed == session and llm.has_session(tmp_path, session)
    assert [message["role"] for message in router.bodies[1]["messages"]] == ["system", "user", "assistant", "user"]
    body = router.bodies[0]
    assert body["model"] == "google/gemini-test" and body["response_format"] == {"type": "json_object"}
    assert router.headers[0]["authorization"] == "Bearer test-key"


def test_unknown_sessions_start_fresh(tmp_path: Path, router: FakeRouter) -> None:
    router.replies = [reply("{}")]
    _text, session = asyncio.run(llm.ask(tmp_path, REQUEST, "system", "revise", resume="old-claude-session"))
    assert session != "old-claude-session" and len(router.bodies[0]["messages"]) == 2


def test_images_are_sent_but_not_kept(tmp_path: Path, router: FakeRouter) -> None:
    image = tmp_path / "slide-01.png"
    image.write_bytes(b"\x89PNG fake")
    router.replies = [reply('{"verdict": "ship", "issues": []}')]
    _text, session = asyncio.run(llm.ask(tmp_path, REQUEST, "reviewer", "review", images=[("Image of slide 0", image)]))

    content = router.bodies[0]["messages"][-1]["content"]
    assert [part.get("text") for part in content[:2]] == ["review", "Image of slide 0"]
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")
    assert session == "" and not (tmp_path / "sessions").exists()


def test_busy_responses_are_retried(tmp_path: Path, router: FakeRouter) -> None:
    router.replies = [(429, {"error": {"message": "rate limited"}}), (503, {}), reply('{"ok": true}')]
    text, _session = asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write"))
    assert text == '{"ok": true}' and len(router.bodies) == 3


def test_dropped_connections_are_retried(tmp_path: Path, router: FakeRouter) -> None:
    lookup_failed = httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")
    router.replies = [lookup_failed, lookup_failed, reply('{"ok": true}')]
    text, _session = asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write"))
    assert text == '{"ok": true}' and len(router.bodies) == 3

    router.replies = [lookup_failed] * llm.RETRY_ATTEMPTS
    with pytest.raises(RuntimeError, match="Could not reach OpenRouter"):
        asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write"))


def test_errors_and_empty_replies_explain_why(tmp_path: Path, router: FakeRouter) -> None:
    router.replies = [(400, {"error": {"message": "model not found"}}), reply("", "length")]
    with pytest.raises(RuntimeError, match="400: model not found"):
        asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write"))
    with pytest.raises(RuntimeError, match="no text .*length"):
        asyncio.run(llm.ask(tmp_path, REQUEST, "system", "write"))


def test_missing_settings_are_reported(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        asyncio.run(llm.ask(tmp_path, {"model": "m"}, "system", "write"))


def test_keys_are_redacted() -> None:
    fake = "sk-or-v1-" + "a" * 40
    assert redact(f"failed with key {fake}") == "failed with key [redacted]"
