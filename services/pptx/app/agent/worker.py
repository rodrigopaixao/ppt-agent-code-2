"""Run the orchestrated presentation pipeline."""

import asyncio
import json
import sys
from pathlib import Path

from app.agent.events import redact
from app.agent.pipeline import run_pipeline


def emit(payload: dict) -> None:
    print(json.dumps(payload), flush=True)


async def run(request: dict) -> None:
    workspace = Path(request["workspace"])
    try:
        session_id = await run_pipeline(workspace, request, emit)
    except Exception as error:
        emit({"event": "done", "ok": False, "session_id": request.get("resume"), "error": redact(str(error))})
        return
    emit({"event": "done", "ok": True, "session_id": session_id, "error": None})


def main() -> None:
    request = json.loads(sys.stdin.read())
    try:
        asyncio.run(run(request))
    except Exception as error:
        emit({"event": "done", "ok": False, "session_id": request.get("resume"), "error": redact(str(error))})
        raise


if __name__ == "__main__":
    main()
