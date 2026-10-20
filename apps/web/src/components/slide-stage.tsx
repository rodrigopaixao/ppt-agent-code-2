"use client";

import { ClipboardEvent, CSSProperties, FocusEvent, FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Deck, DeckPath, getDeck, Job, Region, RegionPara, RequestError, saveDeck } from "@/lib/api";

const SLIDE_WIDTH = 13.333;
const SLIDE_HEIGHT = 7.5;
const BULLET_INDENT = 0.17;
const JUSTIFY = { t: "flex-start", m: "center", b: "flex-end" } as const;
const ALIGN = { l: "left", c: "center", r: "right" } as const;

export type Notice = { kind: "warning" | "error"; text: string; items: string[] };
type Pending = { id: number; region: Region; texts: string[] };
type Point = { x: number; y: number };

export type InlineEditing = ReturnType<typeof useInlineEditing>;

/** Loads the deck behind the previews and saves text edited in place on the slides. */
export function useInlineEditing(job: Job | null, onJob: (job: Job) => void, enabled: boolean, reloadKey: number) {
  const [deck, setDeck] = useState<Deck | null>(null);
  const [regions, setRegions] = useState<Region[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [history, setHistory] = useState<Deck[]>([]);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [saving, setSaving] = useState(false);
  const saved = useRef<Deck | null>(null);
  const undoRef = useRef<() => void>(() => undefined);
  const pendingId = useRef(0);
  const jobId = job?.id;
  const ready = !!job?.spec && (job.status === "complete" || job.status === "rendering");

  useEffect(() => {
    if (!jobId || !ready) return;
    let cancelled = false;
    getDeck(jobId)
      .then((loaded) => {
        if (cancelled) return;
        saved.current = loaded.deck;
        setDeck(loaded.deck);
        setRegions(loaded.regions);
        setHistory([]);
        setPending([]);
      })
      .catch(() => {
        if (cancelled) return;
        saved.current = null;
        setDeck(null);
        setRegions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, job?.finished_at, ready, reloadKey]);

  useEffect(() => {
    if (job?.status === "complete" && !saving) setPending([]);
  }, [job?.status, job?.preview_version, saving]);

  async function persist(next: Deck, pendingEdit?: number) {
    if (!jobId) return false;
    setDeck(next);
    setSaving(true);
    try {
      const result = await saveDeck(jobId, next);
      saved.current = next;
      setRegions(result.regions);
      onJob(result.job);
      setNotice(
        result.warnings.length
          ? { kind: "warning", text: "Some text is now too long for its space. Shorten it so it fits:", items: result.warnings }
          : null,
      );
      return true;
    } catch (error) {
      setDeck(saved.current);
      setPending((items) => items.filter((item) => item.id !== pendingEdit));
      setNotice({
        kind: "error",
        text: error instanceof Error ? error.message : "The edit could not be saved.",
        items: error instanceof RequestError ? error.details : [],
      });
      return false;
    } finally {
      setSaving(false);
    }
  }

  function commit(region: Region, texts: string[]) {
    if (!deck || saving) return;
    const next = applyEdit(deck, region, texts);
    if (!next) return;
    const before = deck;
    setHistory((past) => [...past.slice(-49), before]);
    const id = ++pendingId.current;
    setPending((items) => [...items, { id, region, texts }]);
    void persist(next, id).then((ok) => {
      if (!ok) setHistory((past) => past.slice(0, -1));
    });
  }

  function undo() {
    if (saving || !history.length) return;
    const previous = history[history.length - 1];
    setHistory((past) => past.slice(0, -1));
    void persist(previous);
  }
  undoRef.current = undo;

  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.shiftKey || event.key.toLowerCase() !== "z") return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))) return;
      event.preventDefault();
      undoRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);

  return {
    deck,
    regions,
    pending,
    notice,
    saving,
    editable: enabled && ready && !!deck,
    canUndo: history.length > 0 && !saving,
    commit,
    undo,
    dismiss: () => setNotice(null),
  };
}

export function SlideStage({ src, alt, index, edits, updating }: { src: string; alt: string; index: number; edits: InlineEditing; updating: boolean }) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  const [active, setActive] = useState<{ region: Region; point: Point } | null>(null);
  const [queued, setQueued] = useState<Point | null>(null);

  useLayoutEffect(() => {
    const element = frame.current;
    if (!element) return;
    const measure = () => setScale(element.clientWidth / SLIDE_WIDTH);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setActive(null);
    setQueued(null);
  }, [index]);

  const regions = edits.editable ? edits.regions.filter((region) => region.slide === index) : [];
  const pending = edits.pending.filter((item) => item.region.slide === index);

  useEffect(() => {
    if (!queued || edits.saving) return;
    const target = document.elementFromPoint(queued.x, queued.y)?.getAttribute("data-region");
    if (target != null && regions[Number(target)]) setActive({ region: regions[Number(target)], point: queued });
    setQueued(null);
  }, [edits.saving, queued]);

  return (
    <div className={queued ? "stage-frame waiting" : "stage-frame"} ref={frame}>
      <img className="stage" src={src} alt={alt} />
      {scale > 0 &&
        pending.map((item) => (
          <div key={item.id} className="text-box text-pending" style={boxStyle(item.region, scale)}>
            {item.texts.map((text, line) => {
              const para = item.region.paras[Math.min(line, item.region.paras.length - 1)];
              return (
                <div
                  key={line}
                  className={para.bullet ? "inline-line bullet" : "inline-line"}
                  style={lineStyle(para, scale, line === 0)}
                  dangerouslySetInnerHTML={{ __html: toHtml(item.region, text) }}
                />
              );
            })}
          </div>
        ))}
      {scale > 0 &&
        regions.map((region, position) =>
          active?.region === region ? null : (
            <button
              key={position}
              className="text-hit"
              style={place(region, false)}
              data-region={position}
              aria-label={`Edit text: ${region.paras.map((para) => para.text).join(" ").replace(/\*\*/g, "").slice(0, 80)}`}
              onClick={(event) => {
                const point = { x: event.clientX, y: event.clientY };
                if (edits.saving) setQueued(point);
                else setActive({ region, point });
              }}
            />
          ),
        )}
      {active && scale > 0 && (
        <InlineBox
          key={`${index}-${active.region.paras[0]?.path.join(".")}`}
          region={active.region}
          scale={scale}
          point={active.point}
          total={listLength(edits.deck, active.region)}
          onDone={(texts) => {
            const region = active.region;
            setActive(null);
            if (texts) edits.commit(region, texts);
          }}
        />
      )}
      {updating && <span className="stage-badge">Updating preview…</span>}
    </div>
  );
}

type Line = { id: number; para: RegionPara; html: string };

function InlineBox(props: { region: Region; scale: number; point: Point; total: number; onDone: (texts: string[] | null) => void }) {
  const { region, scale } = props;
  const box = useRef<HTMLDivElement>(null);
  const nodes = useRef(new Map<number, HTMLDivElement>());
  const nextId = useRef(region.paras.length);
  const focusNext = useRef<{ id: number; caret: "start" | "end" } | null>(null);
  const finished = useRef(false);
  const [lines, setLines] = useState<Line[]>(() => region.paras.map((para, id) => ({ id, para, html: toHtml(region, para.text) })));

  useLayoutEffect(() => {
    const range = caretAt(props.point);
    const owner = range && [...nodes.current.values()].find((node) => node.contains(range.startContainer));
    if (range && owner) {
      owner.focus();
      select(range);
    } else {
      const first = nodes.current.get(0);
      first?.focus();
      if (first) placeCaret(first, "end");
    }
  }, []);

  useLayoutEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = null;
    const node = nodes.current.get(target.id);
    if (node) {
      node.focus();
      placeCaret(node, target.caret);
    }
  }, [lines]);

  function finish(save: boolean) {
    if (finished.current) return;
    finished.current = true;
    props.onDone(save ? lines.map((line) => toText(nodes.current.get(line.id))) : null);
  }

  function count() {
    const items = region.items;
    return items ? props.total - (items.end - items.start) + lines.length : lines.length;
  }

  function move(position: number) {
    const node = nodes.current.get(lines[position].id);
    if (!node) return;
    node.focus();
    placeCaret(node, "end");
  }

  function split(node: HTMLDivElement, position: number) {
    let tail = "";
    const selection = window.getSelection();
    if (selection?.rangeCount && node.contains(selection.anchorNode)) {
      const range = selection.getRangeAt(0);
      range.deleteContents();
      const rest = document.createRange();
      rest.setStart(range.startContainer, range.startOffset);
      rest.setEnd(node, node.childNodes.length);
      const holder = document.createElement("div");
      holder.appendChild(rest.extractContents());
      tail = holder.innerHTML;
    }
    const id = nextId.current++;
    focusNext.current = { id, caret: "start" };
    setLines((current) => {
      const next = [...current];
      next.splice(position + 1, 0, { id, para: current[position].para, html: tail });
      return next;
    });
  }

  function merge(position: number) {
    const node = nodes.current.get(lines[position].id);
    const previous = nodes.current.get(lines[position - 1].id);
    if (!node || !previous) return;
    previous.focus();
    placeCaret(previous, "end");
    const selection = window.getSelection();
    const caret = selection?.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    while (node.firstChild) previous.appendChild(node.firstChild);
    if (caret) select(caret);
    const removed = lines[position].id;
    setLines((current) => current.filter((line) => line.id !== removed));
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>, position: number) {
    const key = event.key;
    const node = event.currentTarget;
    const line = lines[position];
    if (key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      finish(false);
    } else if ((event.metaKey || event.ctrlKey) && ["b", "i", "u"].includes(key.toLowerCase())) {
      if (key.toLowerCase() !== "b" || line.para.bold || region.title) event.preventDefault();
    } else if (key === "Tab") {
      event.preventDefault();
      const target = position + (event.shiftKey ? -1 : 1);
      if (target >= 0 && target < lines.length) move(target);
      else finish(true);
    } else if (key === "Enter") {
      event.preventDefault();
      if (region.items) {
        if (count() < region.items.high) split(node, position);
      } else if (position + 1 < lines.length) {
        move(position + 1);
      } else {
        finish(true);
      }
    } else if (key === "Backspace" && region.items && position > 0 && caretAtStart(node) && count() > region.items.low) {
      event.preventDefault();
      merge(position);
    }
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain").replace(/\s+/g, " ");
    document.execCommand("insertText", false, text);
  }

  function onInput(event: FormEvent<HTMLDivElement>) {
    if (!region.title || (event.nativeEvent as InputEvent).isComposing) return;
    const node = event.currentTarget;
    const html = toHtml(region, node.textContent ?? "");
    if (node.innerHTML === html) return;
    const offset = caretOffset(node);
    node.innerHTML = html;
    if (offset != null) placeCaretAt(node, offset);
  }

  return (
    <div
      ref={box}
      className="text-box editing"
      style={boxStyle(region, scale)}
      onBlur={(event: FocusEvent<HTMLDivElement>) => {
        if (!box.current?.contains(event.relatedTarget as Node | null)) finish(true);
      }}
    >
      {lines.map((line, position) => (
        <div
          key={line.id}
          ref={(node) => {
            if (node) nodes.current.set(line.id, node);
            else nodes.current.delete(line.id);
          }}
          className={line.para.bullet ? "inline-line bullet" : "inline-line"}
          style={lineStyle(line.para, scale, position === 0)}
          contentEditable
          suppressContentEditableWarning
          role="textbox"
          aria-label={region.items ? `Point ${region.items.start + position + 1}` : "Slide text"}
          spellCheck
          onKeyDown={(event) => onKeyDown(event, position)}
          onPaste={onPaste}
          onInput={onInput}
          dangerouslySetInnerHTML={{ __html: line.html }}
        />
      ))}
    </div>
  );
}

export function applyEdit(deck: Deck, region: Region, texts: string[]): Deck | null {
  const next = structuredClone(deck);
  if (region.title) {
    const text = texts[0] ?? "";
    const cut = text.indexOf("|");
    if (cut >= 0) {
      write(next, region.title.label, text.slice(0, cut).trim());
      write(next, region.title.headline, text.slice(cut + 1).trim());
    } else {
      write(next, region.title.headline, text);
    }
  } else if (region.items) {
    const list = read(next, region.items.path);
    const items = Array.isArray(list) ? [...list] : [];
    items.splice(region.items.start, region.items.end - region.items.start, ...texts.filter(Boolean));
    write(next, region.items.path, items.length ? items : undefined);
  } else {
    region.paras.forEach((para, position) => {
      const value = texts[position] ?? "";
      const old = read(next, para.path);
      [para.path, ...para.also].forEach((path) => write(next, path, value));
      if (para.path[0] === "sections" && para.path[2] === "name" && typeof old === "string" && old !== value) {
        next.slides.forEach((slide) => {
          if (slide.section === old) slide.section = value;
        });
      }
    });
  }
  return JSON.stringify(next) === JSON.stringify(deck) ? null : next;
}

function read(document: unknown, path: DeckPath): unknown {
  return path.reduce<unknown>((value, key) => (value == null ? undefined : (value as Record<string | number, unknown>)[key]), document);
}

function write(document: unknown, path: DeckPath, value: unknown) {
  const parent = read(document, path.slice(0, -1)) as Record<string | number, unknown> | undefined;
  if (!parent) return;
  const key = path[path.length - 1];
  if ((value === "" || value === undefined) && !Array.isArray(parent)) delete parent[key];
  else parent[key] = value ?? "";
}

function listLength(deck: Deck | null, region: Region) {
  const list = region.items && deck ? read(deck, region.items.path) : null;
  return Array.isArray(list) ? list.length : 0;
}

function percent(value: number) {
  return `${value * 100}%`;
}

function place(region: Region, grow: boolean): CSSProperties {
  const [x, y, width, height] = region.box;
  const style: CSSProperties = { left: percent(x / SLIDE_WIDTH), width: percent(width / SLIDE_WIDTH) };
  if (region.anchor === "b") style.bottom = percent((SLIDE_HEIGHT - y - height) / SLIDE_HEIGHT);
  else style.top = percent(y / SLIDE_HEIGHT);
  if (grow) style.minHeight = percent(height / SLIDE_HEIGHT);
  else style.height = percent(height / SLIDE_HEIGHT);
  return style;
}

function boxStyle(region: Region, scale: number): CSSProperties {
  const [left, right, top, bottom] = region.inset.map((inches) => inches * scale);
  return {
    ...place(region, true),
    padding: `${top}px ${right}px ${bottom}px ${left}px`,
    background: `#${region.fill}`,
    justifyContent: JUSTIFY[region.anchor],
  };
}

function lineStyle(para: RegionPara, scale: number, first: boolean): CSSProperties {
  const points = (value: number) => (value / 72) * scale;
  return {
    fontSize: points(para.size),
    fontWeight: para.bold ? 700 : 400,
    fontStyle: para.italic ? "italic" : undefined,
    color: `#${para.color}`,
    textAlign: ALIGN[para.align],
    textTransform: para.caps ? "uppercase" : undefined,
    letterSpacing: para.spacing ? points(para.spacing / 100) : undefined,
    marginTop: first ? 0 : points(para.space_before),
    paddingLeft: para.bullet ? BULLET_INDENT * scale : undefined,
    ["--accent" as string]: para.accent ? `#${para.accent}` : "inherit",
  };
}

function escapeHtml(text: string) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function toHtml(region: Region, text: string) {
  if (region.title) {
    const cut = text.indexOf(" | ");
    if (cut < 0) return escapeHtml(text);
    return `<span style="color:#${region.title.accent}">${escapeHtml(text.slice(0, cut + 3))}</span>${escapeHtml(text.slice(cut + 3))}`;
  }
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

function markdown(node: Node, bold: boolean): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (!(node instanceof HTMLElement)) return "";
  if (node.tagName === "BR") return " ";
  const weight = node.style.fontWeight;
  const strong = node.tagName === "B" || node.tagName === "STRONG" || weight === "bold" || Number(weight) >= 600;
  const inner = Array.from(node.childNodes)
    .map((child) => markdown(child, bold || strong))
    .join("");
  if (!strong || bold) return inner;
  const [, lead, core, trail] = inner.match(/^(\s*)([\s\S]*?)(\s*)$/) ?? ["", "", inner, ""];
  return core ? `${lead}**${core}**${trail}` : inner;
}

function toText(node?: HTMLElement | null) {
  if (!node) return "";
  return Array.from(node.childNodes)
    .map((child) => markdown(child, false))
    .join("")
    .replace(/\u00a0/g, " ")
    .replace(/\*\*\*\*/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function caretAt(point: Point): Range | null {
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  if (typeof document.caretRangeFromPoint === "function") return document.caretRangeFromPoint(point.x, point.y);
  const position = doc.caretPositionFromPoint?.(point.x, point.y);
  if (!position) return null;
  const range = document.createRange();
  range.setStart(position.offsetNode, position.offset);
  return range;
}

function select(range: Range) {
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function placeCaret(node: HTMLElement, where: "start" | "end") {
  const range = document.createRange();
  range.selectNodeContents(node);
  range.collapse(where === "start");
  select(range);
}

function caretOffset(node: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount) return null;
  const range = selection.getRangeAt(0);
  const before = document.createRange();
  before.selectNodeContents(node);
  before.setEnd(range.endContainer, range.endOffset);
  return before.toString().length;
}

function placeCaretAt(node: HTMLElement, offset: number) {
  const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  let remaining = offset;
  for (const [position, text] of texts.entries()) {
    const length = text.length;
    if (remaining < length || (remaining === length && position === texts.length - 1)) {
      const range = document.createRange();
      range.setStart(text, remaining);
      range.collapse(true);
      select(range);
      return;
    }
    remaining -= length;
  }
  placeCaret(node, "end");
}

function caretAtStart(node: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !selection.isCollapsed) return false;
  const range = selection.getRangeAt(0);
  const before = document.createRange();
  before.selectNodeContents(node);
  before.setEnd(range.startContainer, range.startOffset);
  return before.toString().length === 0;
}
