"use client";

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { Editor, Messages } from "@/components/editor";
import { SlideStage, useInlineEditing } from "@/components/slide-stage";
import { Steps } from "@/components/steps";
import { API_URL, createDeck, getJob, Job, reviseDeck } from "@/lib/api";

const ACTIVE = new Set(["queued", "extracting", "planning", "building", "previewing"]);
const POLLED = new Set([...ACTIVE, "rendering"]);
const LAST_JOB_KEY = "deck-studio:last-job";

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [revision, setRevision] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const edits = useInlineEditing(job, setJob, !editing, reloadKey);

  useEffect(() => {
    const saved = window.localStorage.getItem(LAST_JOB_KEY);
    if (!saved) return;
    getJob(saved)
      .then((restored) => {
        setJob(restored);
        if (restored.status === "failed") setError(restored.error ?? "Generation failed.");
      })
      .catch(() => window.localStorage.removeItem(LAST_JOB_KEY));
  }, []);

  useEffect(() => {
    if (!job || !POLLED.has(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJob(job.id);
        setJob(next);
        if (next.status === "failed") setError(next.error ?? "Generation failed.");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not read job status.");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  const spec = job?.spec;
  const current = spec?.slides[selected];
  const running = !!job && ACTIVE.has(job.status);
  const occupied = !!job && POLLED.has(job.status);
  const canGenerate = prompt.trim().length >= 5 && !busy && !occupied && !editing;
  const version = job?.preview_version ?? 0;
  const statusText = useMemo(() => job?.message ?? "Ready", [job]);

  async function generate() {
    if (!canGenerate) return;
    setBusy(true);
    setError("");
    try {
      const created = await createDeck(prompt, files);
      window.localStorage.setItem(LAST_JOB_KEY, created.id);
      setJob(created);
      setSelected(0);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start generation.");
    } finally {
      setBusy(false);
    }
  }

  async function revise() {
    if (!job || !revision.trim()) return;
    setBusy(true);
    setError("");
    try {
      setJob(await reviseDeck(job.id, revision));
      setRevision("");
      setSelected(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revision failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <span className="eyebrow">LOCAL PRESENTATION WORKSPACE</span>
          <h1>Deck Studio</h1>
        </div>
        <div className="status">
          <span className={job?.status === "failed" ? "dot error-dot" : "dot"} />
          {statusText}
        </div>
      </header>

      <section className={editing ? "workspace editing" : "workspace"}>
        <aside className="composer panel" hidden={editing}>
          <div>
            <p className="step">01 · Brief</p>
            <h2>What should the deck communicate?</h2>
          </div>
          <textarea
            aria-label="Presentation request"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Create an executive-ready deck explaining…"
          />
          <div className="row">
            <button className="secondary" onClick={() => fileRef.current?.click()}>
              Add sources
            </button>
            <input
              ref={fileRef}
              hidden
              multiple
              accept=".pdf,.docx,.txt"
              type="file"
              onChange={(event: ChangeEvent<HTMLInputElement>) =>
                setFiles(Array.from(event.target.files ?? []))
              }
            />
          </div>
          {files.length > 0 && (
            <div className="file-list">
              {files.map((file) => (
                <span key={`${file.name}-${file.size}`}>{file.name}</span>
              ))}
            </div>
          )}
          <button className="primary" disabled={!canGenerate} onClick={generate}>
            {job && ACTIVE.has(job.status) ? `Working · ${job.progress}%` : "Create presentation"}
          </button>
          <p className="notice">
            Prompts and extracted source text are sent to OpenRouter. Files and generated decks stay
            on this computer.
          </p>
          {spec && (
            <div className="revision">
              <p className="step">02 · Refine</p>
              <textarea
                aria-label="Revision request"
                value={revision}
                onChange={(event) => setRevision(event.target.value)}
                placeholder="Make the narrative more concise…"
              />
              <button
                className="secondary"
                disabled={busy || !revision.trim() || !job || occupied || editing}
                onClick={revise}
              >
                Apply revision
              </button>
            </div>
          )}
          {error && <p className="error-message">{error}</p>}
        </aside>

        <section className="canvas panel">
          {!spec ? (
            <div className="empty">
              <div className="empty-mark">P</div>
              <h2>
                {job?.status === "failed"
                  ? "Generation failed"
                  : job
                    ? "Designing the deck"
                    : "Your presentation will appear here"}
              </h2>
              <p>The agent plans the storyline, writes every slide, checks layout and facts, then reviews the rendered deck.</p>
              <Steps job={job} running={running} />
              {job?.status === "failed" && error && <p className="error-message">{error}</p>}
            </div>
          ) : (
            <>
              <div className="canvas-head">
                <div>
                  <p className="step">03 · Review</p>
                  <h2>{spec.title}</h2>
                </div>
                <div className="head-actions">
                  {!editing && job?.status === "complete" && (
                    <button className="secondary" disabled={edits.saving} onClick={() => setEditing(true)}>
                      Edit slides
                    </button>
                  )}
                  {job?.download_url ? (
                    <a className="primary download" href={`${API_URL}${job.download_url}`}>
                      Download .pptx
                    </a>
                  ) : (
                    job?.status === "rendering" && <span className="primary download pending-download">Saving…</span>
                  )}
                </div>
              </div>
              {editing && job ? (
                <Editor
                  job={job}
                  onJob={setJob}
                  onClose={() => {
                    setEditing(false);
                    setSelected(0);
                    setReloadKey((key) => key + 1);
                  }}
                />
              ) : (
                <div className="deck">
                  <nav className="thumbnails" aria-label="Slides">
                    {spec.slides.map((slide, index) => (
                      <button
                        key={`${index}-${slide.title}`}
                        className={index === selected ? "thumbnail selected" : "thumbnail"}
                        onClick={() => setSelected(index)}
                      >
                        <span>{index + 1}</span>
                        {job?.preview_urls[index] ? (
                          <img src={`${API_URL}${job.preview_urls[index]}?v=${version}`} alt="" />
                        ) : (
                          <strong>{slide.title}</strong>
                        )}
                      </button>
                    ))}
                  </nav>
                  {current && (
                    <div className="stage-wrap">
                      {job?.preview_urls[selected] ? (
                        <SlideStage
                          src={`${API_URL}${job.preview_urls[selected]}?v=${version}`}
                          alt={current.title}
                          index={selected}
                          edits={edits}
                          updating={job.status === "rendering"}
                        />
                      ) : (
                        <div className="stage missing">{current.title}</div>
                      )}
                      {edits.editable && (
                        <div className="stage-tools">
                          <span>Click any text on the slide to edit it. Press Enter to add a bullet, Esc to cancel.</span>
                          <button className="secondary" disabled={!edits.canUndo} onClick={edits.undo}>
                            Undo
                          </button>
                        </div>
                      )}
                      {edits.notice && (
                        <div className={edits.notice.kind === "error" ? "error-message" : "warning-message"}>
                          {edits.notice.text}
                          <Messages items={edits.notice.items} onSelect={setSelected} />
                        </div>
                      )}
                      <Steps job={job} running={running} />
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </section>
      </section>
    </main>
  );
}