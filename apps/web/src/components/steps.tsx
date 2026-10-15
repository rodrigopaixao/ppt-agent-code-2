"use client";

import { useEffect, useState } from "react";
import { Job, Step } from "@/lib/api";

type State = "done" | "active" | "failed";

export function Steps({ job, running }: { job: Job | null; running: boolean }) {
  const [open, setOpen] = useState(running);
  const now = useNow(running);

  useEffect(() => setOpen(running), [running]);

  const steps = (job?.activity ?? []).filter((step): step is Step => typeof step === "object" && !!step?.text);
  if (!job || !steps.length) return null;

  const failed = job.status === "failed";
  const start = Date.parse(job.started_at ?? steps[0].at);
  const end = job.finished_at ? Date.parse(job.finished_at) : now;
  const current = steps[steps.length - 1];

  return (
    <section className="steps" aria-label="Agent steps">
      <button className="steps-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        {running ? <span className="spinner" aria-hidden /> : <StepIcon state={failed ? "failed" : "done"} />}
        <span className={running ? "steps-title shimmer" : "steps-title"}>
          {running ? current.text : failed ? `Stopped after ${duration(end - start)}` : `Worked for ${duration(end - start)}`}
        </span>
        <span className="steps-meta">
          {running && <span>{duration(end - start)}</span>}
          <span>
            {steps.length} {steps.length === 1 ? "step" : "steps"}
          </span>
          <Chevron open={open} />
        </span>
      </button>
      {open && (
        <ol className="steps-list">
          {steps.map((step, index) => {
            const last = index === steps.length - 1;
            const state: State = !last ? "done" : running ? "active" : failed ? "failed" : "done";
            const finished = last ? end : Date.parse(steps[index + 1].at);
            return <StepRow key={`${index}-${step.at}`} step={step} state={state} elapsed={finished - Date.parse(step.at)} />;
          })}
        </ol>
      )}
    </section>
  );
}

function StepRow({ step, state, elapsed }: { step: Step; state: State; elapsed: number }) {
  const [expanded, setExpanded] = useState(false);
  const title = (
    <>
      {state === "active" ? <span className="spinner" aria-hidden /> : <StepIcon state={state} />}
      <span className={state === "active" ? "step-text shimmer" : "step-text"}>{step.text}</span>
      <span className="step-time">{duration(elapsed)}</span>
      {step.detail && <Chevron open={expanded} />}
    </>
  );
  return (
    <li className={`step-row ${state}`}>
      {step.detail ? (
        <button className="step-line" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {title}
        </button>
      ) : (
        <div className="step-line">{title}</div>
      )}
      {step.detail && expanded && <div className="step-detail">{step.detail}</div>}
    </li>
  );
}

function StepIcon({ state }: { state: State }) {
  if (state === "failed") {
    return (
      <svg className="step-icon failed" viewBox="0 0 16 16" aria-hidden>
        <circle cx="8" cy="8" r="7" />
        <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
      </svg>
    );
  }
  return (
    <svg className="step-icon" viewBox="0 0 16 16" aria-hidden>
      <circle cx="8" cy="8" r="7" />
      <path d="M5 8.2l2 2 4-4.4" />
    </svg>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className={open ? "chevron open" : "chevron"} viewBox="0 0 16 16" aria-hidden>
      <path d="M6 4l4 4-4 4" />
    </svg>
  );
}

function useNow(ticking: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setNow(Date.now());
    if (!ticking) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);
  return now;
}

function duration(milliseconds: number) {
  const seconds = Math.max(0, Math.round(milliseconds / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}
