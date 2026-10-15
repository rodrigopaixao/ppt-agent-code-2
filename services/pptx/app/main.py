import asyncio
import json
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.agent.deckspec import editor_schema, structure_errors
from app.config import settings
from app.models.presentation import RevisionRequest
from app.pptx.inspector import inspect_template
from app.services.documents import extract_uploads
from app.services.jobs import BUSY, RUNNING, Job, JobManager


app = FastAPI(title="Template PPTX Service", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):3000",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
manager = JobManager(settings)


def require_job(job_id: str) -> Job:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Presentation job not found.")
    return job


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "template_ready": manager.template_path.exists(),
        "model_configured": bool(settings.anthropic_api_key and settings.anthropic_api_key != "<API_KEY>"),
    }


@app.get("/api/template")
def template_info() -> dict:
    if not manager.template_path.exists():
        raise HTTPException(status_code=404, detail="No authorized template is configured.")
    return inspect_template(manager.template_path)


@app.post("/api/jobs", status_code=202)
async def create_job(
    background_tasks: BackgroundTasks,
    prompt: str = Form(min_length=5, max_length=8000),
    slide_count: Optional[int] = Form(default=None),
    files: List[UploadFile] = File(default=[]),
) -> dict:
    if not manager.template_path.exists():
        raise HTTPException(
            status_code=409,
            detail="Template not found. Add the authorized template or run `npm run template:demo`.",
        )
    source_text, source_names = await extract_uploads(
        files, settings.max_upload_bytes, settings.max_extracted_chars
    )
    if slide_count is not None and not 2 <= slide_count <= 30:
        raise HTTPException(status_code=422, detail="slide_count must be between 2 and 30.")
    job = manager.create(prompt, source_text, source_names, slide_count or 0)
    background_tasks.add_task(manager.generate, job)
    return manager.public(job)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return manager.public(require_job(job_id))


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = require_job(job_id)

    async def stream():
        previous = None
        while True:
            payload = manager.public(job)
            encoded = json.dumps(payload)
            if encoded != previous:
                yield f"data: {encoded}\n\n"
                previous = encoded
            if job.status in {"complete", "failed"}:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


def require_deck(job: Job) -> dict:
    deck = manager.deck(job)
    if deck is None:
        raise HTTPException(status_code=404, detail="This presentation was made before slide editing was available.")
    return deck


@app.get("/api/jobs/{job_id}/deck")
def get_deck(job_id: str) -> dict:
    job = require_job(job_id)
    deck = require_deck(job)
    if job.status in RUNNING:
        raise HTTPException(status_code=409, detail="Wait for the current run to finish before editing.")
    return {"deck": deck, "schema": editor_schema(), "regions": manager.regions(job)}


@app.put("/api/jobs/{job_id}/deck")
def update_deck(job_id: str, background_tasks: BackgroundTasks, payload: dict = Body(...)) -> dict:
    job = require_job(job_id)
    require_deck(job)
    if job.status in RUNNING:
        raise HTTPException(status_code=409, detail="Wait for the current run to finish before saving edits.")
    deck = payload.get("deck")
    errors = structure_errors(deck, editorial=False)
    if errors:
        raise HTTPException(status_code=422, detail={"message": "Some fields need attention.", "errors": errors[:20]})
    try:
        warnings, regions = manager.save_deck(job, deck)
    except Exception as error:
        raise HTTPException(status_code=422, detail={"message": "The slides could not be built from these edits.", "errors": [str(error)]}) from error
    background_tasks.add_task(manager.render_edit, job)
    return {"job": manager.public(job), "warnings": warnings, "regions": regions}


@app.post("/api/jobs/{job_id}/revise", status_code=202)
def revise_job(
    job_id: str, request: RevisionRequest, background_tasks: BackgroundTasks
) -> dict:
    job = require_job(job_id)
    if not job.spec or job.status in BUSY:
        raise HTTPException(status_code=409, detail="The presentation is not ready to revise.")
    background_tasks.add_task(manager.revise, job, request.instruction)
    manager.update(job, "queued", 5, "Revision queued")
    return manager.public(job)


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    job = require_job(job_id)
    path = manager.deck_path(job)
    if job.status != "complete" or not path.exists():
        raise HTTPException(status_code=409, detail="The presentation is not ready.")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename="presentation.pptx",
    )


@app.get("/api/jobs/{job_id}/previews/{filename}")
def preview(job_id: str, filename: str) -> FileResponse:
    job = require_job(job_id)
    allowed = {path.name: path for path in job.preview_files}
    path = allowed.get(Path(filename).name)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Preview not found.")
    return FileResponse(path)
