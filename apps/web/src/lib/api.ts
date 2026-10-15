export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ContentBlock = {
  kind: "bullets" | "paragraph" | "quote" | "stat";
  heading?: string | null;
  text?: string | null;
  items: string[];
};

export type Slide = {
  layout: string;
  title: string;
  subtitle?: string | null;
  blocks: ContentBlock[];
  speaker_notes?: string | null;
  sources: string[];
};

export type PresentationSpec = {
  title: string;
  subtitle?: string | null;
  slides: Slide[];
};

export type Step = {
  text: string;
  detail: string;
  at: string;
};

export type Job = {
  id: string;
  status: "queued" | "extracting" | "planning" | "building" | "previewing" | "rendering" | "complete" | "failed";
  progress: number;
  message: string;
  error?: string | null;
  activity: Step[];
  started_at?: string | null;
  finished_at?: string | null;
  spec?: PresentationSpec | null;
  preview_urls: string[];
  preview_version: number;
  download_url?: string | null;
};

export type FieldSpec =
  | { kind: "str"; limit: number; required: boolean }
  | { kind: "numbers"; required: boolean }
  | { kind: "list"; item: FieldSpec; low: number; high: number; required: boolean }
  | { kind: "obj"; fields: Record<string, FieldSpec>; required: boolean };

export type DeckSlide = { type: string; [field: string]: unknown };

export type Deck = {
  storyline?: Record<string, string>;
  cover: { title: string; subtitle?: string; date?: string };
  sections: { name: string; summary: string }[];
  slides: DeckSlide[];
};

export type EditorSchema = {
  header: Record<string, FieldSpec>;
  cover: FieldSpec;
  sections: FieldSpec;
  chart_types: string[];
  types: Record<string, { use: string; fields: Record<string, FieldSpec>; example: Record<string, unknown> }>;
};

export type DeckPath = (string | number)[];

export type RegionPara = {
  path: DeckPath;
  also: DeckPath[];
  text: string;
  size: number;
  bold: boolean;
  color: string;
  accent: string;
  align: "l" | "c" | "r";
  bullet: boolean;
  space_before: number;
  caps: boolean;
  spacing: number;
};

/** A piece of text on a slide preview: where it is drawn (inches) and which deck fields it shows. */
export type Region = {
  slide: number;
  box: [number, number, number, number];
  inset: [number, number, number, number];
  anchor: "t" | "m" | "b";
  fill: string;
  title: { label: DeckPath; headline: DeckPath; accent: string } | null;
  items: { path: DeckPath; start: number; end: number; low: number; high: number } | null;
  paras: RegionPara[];
};

export class RequestError extends Error {
  constructor(message: string, readonly details: string[] = []) {
    super(message);
  }
}

async function checked(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      throw new RequestError(detail.message ?? "Request failed.", detail.errors ?? []);
    }
    throw new RequestError(typeof detail === "string" ? detail : body.error ?? `Request failed (${response.status})`);
  }
  return response;
}

export async function createDeck(prompt: string, files: File[]) {
  const form = new FormData();
  form.set("prompt", prompt);
  files.forEach((file) => form.append("files", file));
  const response = await checked(await fetch(`${API_URL}/api/jobs`, { method: "POST", body: form }));
  return (await response.json()) as Job;
}

export async function getJob(id: string) {
  const response = await checked(await fetch(`${API_URL}/api/jobs/${id}`, { cache: "no-store" }));
  return (await response.json()) as Job;
}

export async function getDeck(id: string) {
  const response = await checked(await fetch(`${API_URL}/api/jobs/${id}/deck`, { cache: "no-store" }));
  return (await response.json()) as { deck: Deck; schema: EditorSchema; regions: Region[] };
}

export async function saveDeck(id: string, deck: Deck) {
  const response = await checked(
    await fetch(`${API_URL}/api/jobs/${id}/deck`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ deck }),
    }),
  );
  return (await response.json()) as { job: Job; warnings: string[]; regions: Region[] };
}

export async function reviseDeck(id: string, instruction: string) {
  const response = await checked(
    await fetch(`${API_URL}/api/jobs/${id}/revise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    }),
  );
  return (await response.json()) as Job;
}
