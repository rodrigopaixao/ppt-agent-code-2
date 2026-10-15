"""Prepare a workspace and run the presentation pipeline in the agent runtime."""

import json
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER

from app.agent.events import redact
from app.models.presentation import LayoutName, PresentationSpec, SlideSpec

TITLE_TYPES = {PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE}


def prepare_workspace(workspace: Path, template_path: Path, prompt: str, source_text: str, *, fresh: bool) -> None:
    if fresh:
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        shutil.copy(template_path, workspace / "template.pptx")
    (workspace / "sources.md").write_text(source_text or "No source documents were attached.", encoding="utf-8")
    (workspace / "request.md").write_text(prompt, encoding="utf-8")


def presentation_spec(path: Path) -> PresentationSpec:
    presentation = Presentation(str(path))
    slides = []
    for slide in presentation.slides:
        slides.append(SlideSpec(layout=LayoutName.TITLE_CONTENT, title=_slide_title(slide)[:140] or "Untitled slide"))
    if not slides:
        raise RuntimeError("The pipeline produced a presentation with no slides.")
    return PresentationSpec(title=slides[0].title, slides=slides)


def _slide_title(slide) -> str:
    texts = []
    for shape in slide.placeholders:
        if not shape.has_text_frame or not shape.text_frame.text.strip():
            continue
        text = " ".join(shape.text_frame.text.split())
        if shape.placeholder_format.type in TITLE_TYPES:
            return text
        if not text.isdigit():
            texts.append((shape.top or 0, text))
    if texts:
        return min(texts, key=lambda item: item[0])[1]
    for shape in slide.shapes:
        if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
            return shape.text_frame.text.strip().splitlines()[0]
    return ""


def run_agent(
    *,
    agent_python: Path,
    app_dir: Path,
    workspace: Path,
    prompt: str,
    revision: Optional[str],
    slide_count: int,
    api_key: str,
    base_url: str,
    model: str,
    resume: Optional[str],
    on_activity: Callable[[str, str], None],
) -> str:
    if not agent_python.exists():
        raise RuntimeError("The Claude Agent SDK runtime is missing. Run `npm run setup` with Python 3.12 available.")
    request = {
        "workspace": str(workspace),
        "prompt": prompt,
        "revision": revision,
        "slide_count": slide_count,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "resume": resume,
    }
    process = subprocess.Popen(
        [str(agent_python), "-m", "app.agent.worker"],
        cwd=app_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PATH": f"/opt/homebrew/bin:{os.environ.get('PATH', '')}"},
    )
    assert process.stdin and process.stdout and process.stderr
    process.stdin.write(json.dumps(request))
    process.stdin.close()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    done = None
    deadline = time.time() + 2400
    while time.time() < deadline and not done:
        if not selector.get_map():
            break
        events = selector.select(timeout=0.5)
        if not events and process.poll() is not None:
            break
        for key, _ in events:
            line = key.fileobj.readline()
            if line == "":
                selector.unregister(key.fileobj)
                continue
            done = _consume(line, on_activity) or done
    if not done and time.time() >= deadline:
        process.kill()
        raise RuntimeError("The presentation pipeline timed out after 40 minutes.")
    stderr = redact(process.stderr.read() or "")
    process.wait(timeout=10)
    if not done:
        raise RuntimeError(stderr[:500] or f"The pipeline exited with status {process.returncode}.")
    if not done["ok"]:
        raise RuntimeError(done.get("error") or stderr[:500] or "The pipeline failed.")
    return done.get("session_id") or ""


def _consume(line: str, on_activity: Callable[[str, str], None]) -> Optional[dict]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        on_activity(redact(line.strip())[:180], "")
        return None
    if event.get("event") == "activity" and event.get("text"):
        on_activity(event["text"], redact(str(event.get("detail") or "")))
    if event.get("event") == "done":
        return event
    return None
