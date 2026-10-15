import json
import os
import shutil
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.agent.events import redact
from app.agent.renderer import build
from app.agent.session import prepare_workspace, presentation_spec, run_agent
from app.config import Settings
from app.models.presentation import PresentationSpec
from app.pptx.preview import render_previews


@dataclass
class Job:
    id: str
    prompt: str
    source_text: str
    source_names: List[str]
    slide_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "queued"
    progress: int = 0
    message: str = "Queued"
    error: Optional[str] = None
    spec: Optional[PresentationSpec] = None
    preview_files: List[Path] = field(default_factory=list)
    activity: List[dict] = field(default_factory=list)
    session_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    preview_version: int = 0
    edits: int = 0


RUNNING = {"queued", "extracting", "planning", "building", "previewing"}
BUSY = RUNNING | {"rendering"}


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_dir = settings.resolve(settings.pptx_data_dir)
        self.template_path = self._template_path()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: Dict[str, Job] = {}
        self.lock = threading.Lock()
        self.rendering: set = set()
        self.save_lock = threading.Lock()

    def _template_path(self) -> Path:
        templates = self.settings.resolve(Path("assets/templates"))
        if templates.exists():
            repository = sorted(path for path in templates.glob("*.pptx") if "repository" in path.name.lower())
            if repository:
                return repository[0]
        configured = self.settings.resolve(self.settings.pptx_template_path)
        if configured.exists():
            return configured
        found = sorted(templates.glob("*.pptx")) if templates.exists() else []
        return found[0] if found else configured

    def create(self, prompt: str, source_text: str, source_names: List[str], slide_count: int) -> Job:
        self.cleanup()
        job = Job(
            id=str(uuid.uuid4()),
            prompt=prompt,
            source_text=source_text,
            source_names=source_names,
            slide_count=slide_count,
        )
        with self.lock:
            self.jobs[job.id] = job
        self.save_metadata(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if job is None:
            job = self._restore(job_id)
            if job is not None:
                with self.lock:
                    self.jobs.setdefault(job_id, job)
                    job = self.jobs[job_id]
        return job

    def save_metadata(self, job: Job) -> None:
        metadata = {
            "prompt": job.prompt,
            "source_names": job.source_names,
            "slide_count": job.slide_count,
            "created_at": job.created_at.isoformat(),
            "session_id": job.session_id,
            "activity": job.activity,
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
        }
        (self.directory(job) / "job.json").write_text(json.dumps(metadata), encoding="utf-8")

    def _restore(self, job_id: str) -> Optional[Job]:
        try:
            uuid.UUID(job_id)
        except ValueError:
            return None
        directory = self.data_dir / job_id
        if not directory.is_dir():
            return None
        metadata_path = directory / "job.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        sources_path = directory / "work" / "sources.md"
        job = Job(
            id=job_id,
            prompt=metadata.get("prompt", ""),
            source_text=sources_path.read_text(encoding="utf-8") if sources_path.exists() else "",
            source_names=metadata.get("source_names", []),
            slide_count=metadata.get("slide_count", 8),
            session_id=metadata.get("session_id"),
            activity=[step for step in metadata.get("activity", []) if isinstance(step, dict)],
        )
        if metadata.get("created_at"):
            job.created_at = datetime.fromisoformat(metadata["created_at"])
        if metadata.get("started_at"):
            job.started_at = datetime.fromisoformat(metadata["started_at"])
        if metadata.get("finished_at"):
            job.finished_at = datetime.fromisoformat(metadata["finished_at"])
        deck = directory / "presentation.pptx"
        spec_path = directory / "spec.json"
        if deck.exists() and spec_path.exists():
            job.spec = PresentationSpec.model_validate_json(spec_path.read_text(encoding="utf-8"))
            job.preview_files = sorted((directory / "previews").glob("slide-*"))
            if job.preview_files:
                job.preview_version = int(job.preview_files[0].stat().st_mtime * 1000)
            job.status, job.progress, job.message = "complete", 100, "Ready to review"
            return job
        job.status, job.progress, job.message = "failed", 100, "Generation interrupted"
        job.error = (
            "This run stopped before it finished, usually because the server restarted. "
            "Start the presentation again."
        )
        return job

    def directory(self, job: Job) -> Path:
        path = self.data_dir / job.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def deck_path(self, job: Job) -> Path:
        return self.directory(job) / "presentation.pptx"

    def update(self, job: Job, status: str, progress: int, message: str) -> None:
        with self.lock:
            job.status = status
            job.progress = progress
            job.message = message

    def note(self, job: Job, text: str, detail: str = "") -> None:
        cleaned = " ".join(text.split())[:180]
        if not cleaned:
            return
        with self.lock:
            if not job.activity or job.activity[-1]["text"] != cleaned:
                job.activity.append({"text": cleaned, "detail": detail.strip()[:2000], "at": _iso(_now())})
                job.activity[:] = job.activity[-40:]
            job.message = cleaned

    def workspace(self, job: Job) -> Path:
        return self.directory(job) / "work"

    def agent_python(self) -> Path:
        return self.settings.resolve(Path(".venv312/bin/python"))

    def generate(self, job: Job) -> None:
        self._run_agent(job, revision=None)

    def _run_agent(self, job: Job, revision: Optional[str]) -> None:
        with self.lock:
            job.activity = []
            job.started_at, job.finished_at = _now(), None
        try:
            self.update(job, "planning", 15, "Preparing the workspace")
            if revision is None:
                count = len(job.source_names)
                self.note(
                    job,
                    f"Read {count} source file{'' if count == 1 else 's'}" if count else "No source files attached",
                    "\n".join(job.source_names),
                )
            prepare_workspace(
                self.workspace(job),
                self.template_path,
                job.prompt,
                job.source_text,
                fresh=revision is None,
            )
            self.update(job, "building", 30, "Writing the storyline")
            job.session_id = run_agent(
                agent_python=self.agent_python(),
                app_dir=Path(__file__).resolve().parents[2],
                workspace=self.workspace(job),
                prompt=job.prompt,
                revision=revision,
                slide_count=job.slide_count,
                api_key=self.settings.anthropic_api_key,
                base_url=self.settings.anthropic_base_url,
                model=self.settings.anthropic_model,
                resume=job.session_id if revision else None,
                on_activity=lambda text, detail: self.note(job, text, detail),
            )
            self.finish(job)
        except Exception as error:
            self.fail(job, error)
        finally:
            self.save_metadata(job)

    def finish(self, job: Job) -> None:
        produced = self.workspace(job) / "presentation.pptx"
        if not produced.exists():
            raise RuntimeError("The agent did not write presentation.pptx.")
        self.update(job, "previewing", 85, "Rendering slide previews")
        self.note(job, "Preparing the final deck and previews")
        self.publish(job)
        job.finished_at = _now()
        self.update(job, "complete", 100, "Ready to review")

    def publish(self, job: Job) -> None:
        directory = self.directory(job)
        shutil.copy(self.workspace(job) / "presentation.pptx", self.deck_path(job))
        job.spec = presentation_spec(self.deck_path(job))
        (directory / "spec.json").write_text(
            json.dumps(job.spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        job.preview_files = render_previews(self.deck_path(job), job.spec, directory / "previews")
        job.preview_version = int(_now().timestamp() * 1000)

    def deck(self, job: Job) -> Optional[dict]:
        path = self.workspace(job) / "deck.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def regions(self, job: Job) -> List[dict]:
        """Where each editable piece of text sits on the slides, rebuilt if the deck changed since it was saved."""
        workspace = self.workspace(job)
        deck_path, regions_path = workspace / "deck.json", workspace / "regions.json"
        if regions_path.exists() and regions_path.stat().st_mtime >= deck_path.stat().st_mtime:
            return json.loads(regions_path.read_text(encoding="utf-8"))
        regions: List[dict] = []
        with tempfile.TemporaryDirectory() as scratch:
            build(workspace / "template.pptx", json.loads(deck_path.read_text(encoding="utf-8")), Path(scratch) / "deck.pptx", regions)
        _write_atomic(regions_path, json.dumps(regions))
        return regions

    def save_deck(self, job: Job, deck: dict) -> Tuple[List[str], List[dict]]:
        """Rebuild the deck from edited content; returns the text that could not fit and the new text regions."""
        workspace = self.workspace(job)
        regions: List[dict] = []
        scratch = workspace / f".presentation-{uuid.uuid4().hex}.pptx"
        with self.save_lock:
            try:
                problems = build(workspace / "template.pptx", deck, scratch, regions)
                os.replace(scratch, workspace / "presentation.pptx")
            finally:
                scratch.unlink(missing_ok=True)
            _write_atomic(workspace / "deck.json", json.dumps(deck, indent=2, ensure_ascii=False))
            _write_atomic(workspace / "regions.json", json.dumps(regions))
        with self.lock:
            job.edits += 1
            job.status, job.progress, job.message = "rendering", 90, "Updating previews"
        return problems, regions

    def render_edit(self, job: Job) -> None:
        """Refresh previews after edits. Saves made while this runs are picked up before it reports complete."""
        with self.lock:
            if job.id in self.rendering:
                return
            self.rendering.add(job.id)
        try:
            while True:
                with self.lock:
                    seen = job.edits
                self.publish(job)
                with self.lock:
                    if job.edits == seen:
                        self.rendering.discard(job.id)
                        job.status, job.progress, job.message = "complete", 100, "Ready to review"
                        return
        except Exception as error:
            with self.lock:
                self.rendering.discard(job.id)
            self.fail(job, error)

    def revise(self, job: Job, instruction: str) -> None:
        if not self.deck_path(job).exists() and not (self.workspace(job) / "presentation.pptx").exists():
            raise ValueError("Generate the presentation before revising it.")
        self._run_agent(job, revision=instruction)

    def fail(self, job: Job, error: Exception) -> None:
        with self.lock:
            job.status = "failed"
            job.progress = 100
            job.message = "Generation failed"
            job.error = redact(str(error))
            job.finished_at = _now()

    def cleanup(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        expired = [job for job in self.jobs.values() if job.created_at < cutoff]
        for job in expired:
            shutil.rmtree(self.data_dir / job.id, ignore_errors=True)
            self.jobs.pop(job.id, None)

    @staticmethod
    def public(job: Job) -> dict:
        preview_urls = [
            f"/api/jobs/{job.id}/previews/{path.name}" for path in job.preview_files
        ]
        return {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "message": job.message,
            "error": job.error,
            "spec": job.spec.model_dump(mode="json") if job.spec else None,
            "activity": job.activity,
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "preview_urls": preview_urls,
            "preview_version": job.preview_version,
            "download_url": (
                f"/api/jobs/{job.id}/download" if job.status == "complete" else None
            ),
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return moment.isoformat() if moment else None


def _write_atomic(path: Path, text: str) -> None:
    scratch = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)
