"use client";

import { useEffect, useState } from "react";
import { API_URL, Deck, DeckSlide, EditorSchema, FieldSpec, getDeck, Job, RequestError, saveDeck } from "@/lib/api";

type Item = { key: string; origin: number | null; edited: boolean; slide: DeckSlide };
type Draft = { base: Deck; items: Item[] };
type Context = { schema: EditorSchema; sections: string[]; slide: DeckSlide };
type Fields = Record<string, unknown>;

const TYPE_NAMES: Record<string, string> = {
  executive_summary: "Executive summary",
  kpis: "Key figures",
  cards: "Cards",
  process: "Process",
  roadmap: "Roadmap",
  table: "Table",
  chart: "Chart",
  comparison: "Comparison",
  rows: "Rows",
  strategy_house: "Strategy house",
  timeline: "Dated timeline",
  journey: "Journey map",
  statement: "Statement",
  agenda: "Agenda",
  section: "Section divider",
};

const SINGULAR: Record<string, string> = {
  items: "Item",
  points: "Point",
  steps: "Step",
  lanes: "Lane",
  cells: "Cell",
  periods: "Period",
  categories: "Category",
  series: "Series",
  highlights: "Highlight",
  commentary: "Comment",
  pillars: "Pillar",
  milestones: "Milestone",
  deliverables: "Deliverable",
  meetings: "Meeting",
};

const LABELS: Record<string, string> = {
  label: "Topic label (red)",
  headline: "Headline",
  subheader: "Caption above the visual",
  source: "Source footnote",
  takeaway: "Takeaway banner",
  left_header: "Left column header",
  right_header: "Right column header",
  chart_type: "Chart type",
  chart_title: "Chart title",
  aspiration: "Aspiration (top band)",
  outcome: "Outcome (bottom band)",
  start: "Calendar start (YYYY-MM-DD)",
  end: "End date (YYYY-MM-DD)",
  kind: "Kind: milestone, submission or review",
  milestones_heading: "Milestones row label",
  deliverables_heading: "Deliverables row label",
  meetings_heading: "Meetings row label",
  meeting_name: "Meeting name, e.g. SteerCo",
  via: "Channel on the arrow into this step",
  highlight: "Highlighted step (number)",
};

let counter = 0;
const nextKey = () => `slide-${++counter}`;

export function Editor({ job, onJob, onClose }: { job: Job; onJob: (job: Job) => void; onClose: () => void }) {
  const [schema, setSchema] = useState<EditorSchema | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [selected, setSelected] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loadError, setLoadError] = useState("");
  const [newType, setNewType] = useState("cards");
  const rendering = job.status === "rendering";

  async function load() {
    try {
      const loaded = await getDeck(job.id);
      setSchema(loaded.schema);
      setDraft({
        base: loaded.deck,
        items: loaded.deck.slides.map((slide, index) => ({ key: nextKey(), origin: index + 1, edited: false, slide })),
      });
      setDirty(false);
      setMessage("");
      setErrors([]);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load the slides.");
    }
  }

  useEffect(() => {
    load();
  }, [job.id]);

  if (loadError) {
    return (
      <div className="editor">
        <p className="error-message">{loadError}</p>
        <button className="secondary" onClick={onClose}>
          Back to preview
        </button>
      </div>
    );
  }
  if (!schema || !draft) return <div className="editor editor-loading">Loading slides…</div>;

  const items = draft.items;
  const sectionNames = draft.base.sections.map((section) => section.name);
  const current = selected > 0 ? items[selected - 1] : null;

  function change(next: (draft: Draft) => Draft) {
    setDraft((previous) => previous && next(previous));
    setDirty(true);
    setMessage("");
    setErrors([]);
  }

  function setSlide(index: number, slide: DeckSlide) {
    change((d) => ({
      ...d,
      items: d.items.map((item, i) => (i === index ? { ...item, slide: normalize(slide), edited: true } : item)),
    }));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= items.length) return;
    change((d) => {
      const next = [...d.items];
      [next[index], next[target]] = [next[target], next[index]];
      return { ...d, items: next };
    });
    setSelected(target + 1);
  }

  function duplicate(index: number) {
    change((d) => {
      const copy = { ...d.items[index], key: nextKey(), edited: true, slide: clone(d.items[index].slide) };
      return { ...d, items: [...d.items.slice(0, index + 1), copy, ...d.items.slice(index + 1)] };
    });
    setSelected(index + 2);
  }

  function remove(index: number) {
    if (items.length <= 1) return;
    change((d) => ({ ...d, items: d.items.filter((_, i) => i !== index) }));
    setSelected(Math.min(index + 1, items.length - 1));
  }

  function add(after: number) {
    const reference = after >= 0 ? items[after]?.slide : undefined;
    const slide = blankSlide(schema!, newType, reference, sectionNames[0] ?? "", false);
    change((d) => ({
      ...d,
      items: [...d.items.slice(0, after + 1), { key: nextKey(), origin: null, edited: true, slide }, ...d.items.slice(after + 1)],
    }));
    setSelected(after + 2);
  }

  function setCover(cover: Deck["cover"]) {
    change((d) => ({ ...d, base: { ...d.base, cover } }));
  }

  function setSections(sections: Deck["sections"], renamed?: { from: string; to: string }) {
    change((d) => ({
      base: { ...d.base, sections },
      items: renamed
        ? d.items.map((item) =>
            item.slide.section === renamed.from ? { ...item, slide: { ...item.slide, section: renamed.to } } : item,
          )
        : d.items,
    }));
  }

  async function save() {
    if (!draft) return;
    setSaving(true);
    setMessage("");
    setErrors([]);
    try {
      const result = await saveDeck(job.id, { ...draft.base, slides: draft.items.map((item) => item.slide) });
      setWarnings(result.warnings);
      setDraft((d) => d && { ...d, items: d.items.map((item, index) => ({ ...item, origin: index + 1, edited: false })) });
      setDirty(false);
      onJob(result.job);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not save the changes.");
      setErrors(err instanceof RequestError ? err.details : []);
    } finally {
      setSaving(false);
    }
  }

  function discard() {
    if (window.confirm("Discard all unsaved changes?")) {
      setSelected(0);
      setWarnings([]);
      load();
    }
  }

  function close() {
    if (!dirty || window.confirm("You have unsaved changes. Leave without saving?")) onClose();
  }

  const preview = (origin: number | null) =>
    origin !== null && job.preview_urls[origin] ? `${API_URL}${job.preview_urls[origin]}?v=${job.preview_version}` : null;
  const edits = items.filter((item) => item.edited).length;
  const status = rendering
    ? "Updating previews…"
    : saving
      ? "Saving…"
      : dirty
        ? `Unsaved changes${edits ? ` on ${edits} slide${edits === 1 ? "" : "s"}` : ""}`
        : "All changes saved";
  const stageImage = selected === 0 ? preview(0) : current ? preview(current.origin) : null;
  const context = (slide: DeckSlide): Context => ({ schema, sections: sectionNames, slide });

  return (
    <div className="editor">
      <div className="editor-bar">
        <span className={dirty ? "editor-status unsaved" : "editor-status"}>{status}</span>
        <div className="editor-buttons">
          <button className="secondary" onClick={discard} disabled={!dirty || saving}>
            Discard
          </button>
          <button className="primary" onClick={save} disabled={!dirty || saving || rendering}>
            Save changes
          </button>
          <button className="secondary" onClick={close} disabled={saving}>
            Done
          </button>
        </div>
      </div>

      <div className="editor-grid">
        <nav className="thumbnails" aria-label="Slides">
          <Thumb number={1} title="Cover" image={preview(0)} selected={selected === 0} edited={false} onClick={() => setSelected(0)} />
          {items.map((item, index) => (
            <Thumb
              key={item.key}
              number={index + 2}
              title={String(item.slide.headline || TYPE_NAMES[item.slide.type] || item.slide.type)}
              image={preview(item.origin)}
              selected={selected === index + 1}
              edited={item.edited}
              onClick={() => setSelected(index + 1)}
            />
          ))}
        </nav>

        <div className="editor-stage">
          {stageImage ? (
            <img className={rendering ? "stage stale" : "stage"} src={stageImage} alt="" />
          ) : (
            <div className="stage missing">The preview appears after you save.</div>
          )}
          {current?.edited && stageImage && <p className="stage-note">Showing the last saved version. Save to update the preview.</p>}
          {(message || errors.length > 0) && (
            <div className="error-message">
              <strong>{message}</strong>
              <Messages items={errors} onSelect={setSelected} />
            </div>
          )}
          {warnings.length > 0 && !dirty && (
            <div className="warning-message">
              <strong>Some text is set at the smallest size and may still be tight.</strong>
              <Messages items={warnings} onSelect={setSelected} />
            </div>
          )}
        </div>

        <aside className="editor-panel">
          {selected === 0 || !current ? (
            <>
              <div className="panel-head">
                <strong>Cover and sections</strong>
              </div>
              <div className="panel-body">
                <ObjField
                  spec={schema.cover as Extract<FieldSpec, { kind: "obj" }>}
                  value={draft.base.cover}
                  onChange={(value) => setCover(value as Deck["cover"])}
                  context={context({ type: "cover" })}
                />
                <SectionsEditor sections={draft.base.sections} items={items} onChange={setSections} />
              </div>
            </>
          ) : (
            <>
              <div className="panel-head">
                <strong>
                  Slide {selected + 1} · {TYPE_NAMES[current.slide.type] ?? current.slide.type}
                </strong>
                <div className="panel-tools">
                  <button title="Move up" aria-label="Move up" onClick={() => move(selected - 1, -1)} disabled={selected === 1}>
                    ↑
                  </button>
                  <button title="Move down" aria-label="Move down" onClick={() => move(selected - 1, 1)} disabled={selected === items.length}>
                    ↓
                  </button>
                  <button title="Duplicate" onClick={() => duplicate(selected - 1)}>
                    Duplicate
                  </button>
                  <button title="Delete" onClick={() => remove(selected - 1)} disabled={items.length <= 1}>
                    Delete
                  </button>
                </div>
              </div>
              <div className="panel-body" key={current.key}>
                <SlideFields
                  slide={current.slide}
                  context={context(current.slide)}
                  onChange={(slide) => setSlide(selected - 1, slide)}
                />
              </div>
            </>
          )}
          <div className="panel-foot">
            <select value={newType} onChange={(event) => setNewType(event.target.value)} aria-label="New slide type">
              {Object.keys(schema.types).map((type) => (
                <option key={type} value={type}>
                  {TYPE_NAMES[type] ?? type}
                </option>
              ))}
            </select>
            <button className="secondary" onClick={() => add(selected - 1)} title="Insert a new slide after the selected one">
              Add slide
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Thumb(props: { number: number; title: string; image: string | null; selected: boolean; edited: boolean; onClick: () => void }) {
  return (
    <button className={props.selected ? "thumbnail selected" : "thumbnail"} onClick={props.onClick} title={props.title}>
      <span>{props.number}</span>
      {props.edited && <i className="edited-dot" aria-label="Edited" />}
      {props.image ? <img src={props.image} alt="" /> : <strong>{props.title}</strong>}
    </button>
  );
}

export function Messages({ items, onSelect }: { items: string[]; onSelect: (position: number) => void }) {
  if (!items.length) return null;
  return (
    <ul className="messages">
      {items.map((item, index) => {
        const match = item.match(/^Slide (\d+)/);
        const text = match ? item.replace(/^Slide (\d+)/, `Slide ${Number(match[1]) + 1}`) : item;
        return (
          <li key={index}>
            {match ? <button onClick={() => onSelect(Number(match[1]))}>{text}</button> : text}
          </li>
        );
      })}
    </ul>
  );
}

function SlideFields({ slide, context, onChange }: { slide: DeckSlide; context: Context; onChange: (slide: DeckSlide) => void }) {
  const { schema } = context;
  const header: Record<string, FieldSpec> =
    slide.type === "section"
      ? { section: schema.header.section }
      : slide.type === "agenda"
        ? { label: { kind: "str", limit: 28, required: false }, headline: { kind: "str", limit: 125, required: false } }
        : schema.header;
  const body = schema.types[slide.type]?.fields ?? {};
  const set = (key: string, value: unknown) => onChange(withKey(slide, key, value) as DeckSlide);

  function changeType(type: string) {
    if (type === slide.type) return;
    if (!window.confirm("Changing the slide type replaces the slide body with a starting example. Continue?")) return;
    onChange(blankSlide(schema, type, slide, context.sections[0] ?? "", true));
  }

  return (
    <>
      <label className="field">
        <span className="field-label">Slide type</span>
        <select value={slide.type} onChange={(event) => changeType(event.target.value)}>
          {Object.keys(schema.types).map((type) => (
            <option key={type} value={type}>
              {TYPE_NAMES[type] ?? type}
            </option>
          ))}
        </select>
        <small>{schema.types[slide.type]?.use}</small>
      </label>
      <p className="hint">
        Wrap words in <code>**double asterisks**</code> to make them bold.
      </p>
      {Object.entries(header).map(([key, spec]) => (
        <Field key={key} name={key} spec={spec} value={slide[key]} onChange={(value) => set(key, value)} context={context} />
      ))}
      {slide.type === "agenda" && <p className="hint">The agenda lists the sections. Edit them on the cover.</p>}
      {slide.type === "table" ? (
        <TableEditor slide={slide} onChange={onChange} />
      ) : (
        Object.entries(body).map(([key, spec]) => (
          <Field key={key} name={key} spec={spec} value={slide[key]} onChange={(value) => set(key, value)} context={context} />
        ))
      )}
    </>
  );
}

function Field(props: { name: string; label?: string; spec: FieldSpec; value: unknown; onChange: (value: unknown) => void; context: Context }) {
  const { name, spec, value, onChange, context } = props;
  const label = props.label ?? LABELS[name] ?? humanize(name);
  if (spec.kind === "str") {
    const choices = name === "chart_type" ? context.schema.chart_types : name === "section" ? context.sections : null;
    if (choices) {
      return (
        <label className="field">
          <span className="field-label">{label}</span>
          <select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}>
            {!choices.includes(String(value ?? "")) && <option value="">Choose…</option>}
            {choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
          </select>
        </label>
      );
    }
    return <TextField label={label} limit={spec.limit} required={spec.required} value={value} onChange={onChange} />;
  }
  if (spec.kind === "numbers") {
    const categories = Array.isArray(context.slide.categories) ? (context.slide.categories as unknown[]).map(String) : [];
    return <NumbersField label={label} value={value} categories={categories} onChange={onChange} />;
  }
  if (spec.kind === "list") return <ListField name={name} label={label} spec={spec} value={value} onChange={onChange} context={context} />;
  return <ObjField spec={spec} value={value} onChange={onChange} context={context} />;
}

function TextField(props: { label: string; limit: number; required: boolean; value: unknown; onChange: (value: unknown) => void }) {
  const text = props.value == null ? "" : String(props.value);
  const length = text.replace(/\*\*/g, "").length;
  const update = (next: string) => props.onChange(next === "" && !props.required ? undefined : next);
  return (
    <label className="field">
      <span className="field-label">
        {props.label}
        {!props.required && <em>optional</em>}
        <span className={length > props.limit ? "count over" : "count"}>
          {length}/{props.limit}
        </span>
      </span>
      {props.limit > 60 ? (
        <textarea rows={Math.min(5, Math.max(2, Math.ceil(length / 42)))} value={text} onChange={(event) => update(event.target.value)} />
      ) : (
        <input value={text} onChange={(event) => update(event.target.value)} />
      )}
    </label>
  );
}

function NumbersField(props: { label: string; value: unknown; categories: string[]; onChange: (value: unknown) => void }) {
  const numbers = Array.isArray(props.value) ? (props.value as number[]) : [];
  return (
    <div className="field-group">
      <div className="group-head">{props.label}</div>
      <div className="number-grid">
        {props.categories.map((category, index) => (
          <label key={index} className="field">
            <span className="field-label">{category || `#${index + 1}`}</span>
            <input
              type="number"
              step="any"
              value={numbers[index] ?? ""}
              onChange={(event) => {
                const next = [...numbers];
                next[index] = event.target.value === "" ? 0 : Number(event.target.value);
                props.onChange(next);
              }}
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function ListField(props: {
  name: string;
  label: string;
  spec: Extract<FieldSpec, { kind: "list" }>;
  value: unknown;
  onChange: (value: unknown) => void;
  context: Context;
}) {
  const { name, spec, context } = props;
  const items = Array.isArray(props.value) ? (props.value as unknown[]) : [];
  const singular = SINGULAR[name] ?? humanize(name).replace(/s$/, "");
  const periods = Array.isArray(context.slide.periods) ? (context.slide.periods as unknown[]).map(String) : [];
  const set = (next: unknown[]) => props.onChange(next.length === 0 && !spec.required ? undefined : next);
  const move = (index: number, delta: number) => {
    const next = [...items];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    set(next);
  };
  const simple = spec.item.kind === "str";
  return (
    <div className="field-group">
      <div className="group-head">
        <span>{props.label}</span>
        <span className="count">
          {items.length} of {spec.low}–{spec.high}
        </span>
      </div>
      {items.map((item, index) => {
        const itemLabel = name === "cells" && periods[index] ? periods[index] : `${singular} ${index + 1}`;
        return (
          <div key={index} className={simple ? "list-row" : "list-card"}>
            <div className="list-body">
              {!simple && <div className="card-title">{itemLabel}</div>}
              <Field
                name={name}
                label={simple ? itemLabel : ""}
                spec={spec.item}
                value={item}
                onChange={(value) => set(items.map((existing, i) => (i === index ? value : existing)))}
                context={context}
              />
            </div>
            <div className="row-tools">
              <button title="Move up" aria-label="Move up" disabled={index === 0} onClick={() => move(index, -1)}>
                ↑
              </button>
              <button title="Move down" aria-label="Move down" disabled={index === items.length - 1} onClick={() => move(index, 1)}>
                ↓
              </button>
              <button title="Remove" aria-label="Remove" disabled={items.length <= spec.low} onClick={() => set(items.filter((_, i) => i !== index))}>
                ×
              </button>
            </div>
          </div>
        );
      })}
      {items.length < spec.high && (
        <button className="add" onClick={() => set([...items, makeDefault(spec.item)])}>
          + Add {singular.toLowerCase()}
        </button>
      )}
    </div>
  );
}

function ObjField(props: { spec: Extract<FieldSpec, { kind: "obj" }>; value: unknown; onChange: (value: unknown) => void; context: Context }) {
  const object = (props.value && typeof props.value === "object" ? props.value : {}) as Fields;
  return (
    <div className="field-obj">
      {Object.entries(props.spec.fields).map(([key, spec]) => (
        <Field
          key={key}
          name={key}
          spec={spec}
          value={object[key]}
          onChange={(value) => props.onChange(withKey(object, key, value))}
          context={props.context}
        />
      ))}
    </div>
  );
}

function TableEditor({ slide, onChange }: { slide: DeckSlide; onChange: (slide: DeckSlide) => void }) {
  const columns = (Array.isArray(slide.columns) ? slide.columns : []).map(String);
  const rows = (Array.isArray(slide.rows) ? slide.rows : []).map((row) => (Array.isArray(row) ? row.map((cell) => String(cell ?? "")) : []));
  const update = (nextColumns: string[], nextRows: string[][]) => onChange({ ...slide, columns: nextColumns, rows: nextRows });
  return (
    <div className="field-group">
      <div className="group-head">
        <span>Table</span>
        <span className="count">
          {columns.length} columns · {rows.length} rows
        </span>
      </div>
      <div className="table-editor">
        <table>
          <thead>
            <tr>
              {columns.map((column, c) => (
                <th key={c}>
                  <input value={column} onChange={(event) => update(columns.map((x, i) => (i === c ? event.target.value : x)), rows)} />
                  <button
                    title="Remove column" aria-label="Remove column"
                    disabled={columns.length <= 2}
                    onClick={() => update(columns.filter((_, i) => i !== c), rows.map((row) => row.filter((_, i) => i !== c)))}
                  >
                    ×
                  </button>
                </th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, r) => (
              <tr key={r}>
                {columns.map((_, c) => (
                  <td key={c}>
                    <textarea
                      rows={2}
                      value={row[c] ?? ""}
                      onChange={(event) =>
                        update(columns, rows.map((existing, i) => (i === r ? existing.map((x, j) => (j === c ? event.target.value : x)) : existing)))
                      }
                    />
                  </td>
                ))}
                <td>
                  <button title="Remove row" aria-label="Remove row" disabled={rows.length <= 2} onClick={() => update(columns, rows.filter((_, i) => i !== r))}>
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        {rows.length < 8 && (
          <button className="add" onClick={() => update(columns, [...rows, columns.map(() => "")])}>
            + Add row
          </button>
        )}
        {columns.length < 6 && (
          <button className="add" onClick={() => update([...columns, "New column"], rows.map((row) => [...row, ""]))}>
            + Add column
          </button>
        )}
      </div>
    </div>
  );
}

function SectionsEditor(props: {
  sections: Deck["sections"];
  items: Item[];
  onChange: (sections: Deck["sections"], renamed?: { from: string; to: string }) => void;
}) {
  const { sections, items } = props;
  const usage = (name: string) => items.filter((item) => item.slide.section === name).length;
  return (
    <div className="field-group">
      <div className="group-head">
        <span>Sections</span>
        <span className="count">{sections.length} of 1–6</span>
      </div>
      {sections.map((section, index) => {
        const used = usage(section.name);
        return (
          <div key={index} className="list-card">
            <div className="list-body">
              <div className="card-title">
                Section {index + 1}
                <small>
                  {used} slide{used === 1 ? "" : "s"}
                </small>
              </div>
              <TextField
                label="Name"
                limit={40}
                required
                value={section.name}
                onChange={(value) =>
                  props.onChange(
                    sections.map((s, i) => (i === index ? { ...s, name: String(value ?? "") } : s)),
                    { from: section.name, to: String(value ?? "") },
                  )
                }
              />
              <TextField
                label="Summary"
                limit={120}
                required
                value={section.summary}
                onChange={(value) => props.onChange(sections.map((s, i) => (i === index ? { ...s, summary: String(value ?? "") } : s)))}
              />
            </div>
            <div className="row-tools">
              <button
                title={used ? "Move or delete this section's slides first" : "Remove section"} aria-label="Remove section"
                disabled={used > 0 || sections.length <= 1}
                onClick={() => props.onChange(sections.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </div>
          </div>
        );
      })}
      {sections.length < 6 && (
        <button className="add" onClick={() => props.onChange([...sections, { name: `Section ${sections.length + 1}`, summary: "" }])}>
          + Add section
        </button>
      )}
    </div>
  );
}

function blankSlide(
  schema: EditorSchema,
  type: string,
  reference: DeckSlide | undefined,
  fallbackSection: string,
  keepHeader: boolean,
): DeckSlide {
  const section = String(reference?.section ?? fallbackSection);
  if (type === "section") return { type, section };
  if (type === "agenda") return { type };
  const kept = keepHeader ? reference : undefined;
  const header: Fields = {
    section,
    label: kept?.label ?? "Topic",
    headline: kept?.headline ?? "State the point of this slide as a sentence",
  };
  for (const key of ["subheader", "source", "takeaway"]) {
    if (kept?.[key]) header[key] = kept[key];
  }
  const fields = schema.types[type].fields;
  const body = Object.fromEntries(
    Object.entries(clone(schema.types[type].example)).map(([key, value]) => [
      key,
      fields[key] ? placeholder(key, padded(fields[key], value)) : value,
    ]),
  );
  return normalize({ type, ...header, ...body } as DeckSlide);
}

function placeholder(key: string, value: unknown): unknown {
  if (key === "chart_type" || key === "kind" || key === "highlight") return value;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  if (typeof value === "string") return LABELS[key] ?? SINGULAR[key] ?? humanize(key);
  if (typeof value === "number") return 1;
  if (Array.isArray(value)) {
    return value.map((item, index) => {
      if (typeof item === "number") return index + 1;
      if (typeof item === "string") return `${SINGULAR[key] ?? humanize(key)} ${index + 1}`;
      return placeholder(key, item);
    });
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Fields).map(([field, item]) => [field, placeholder(field, item)]));
  }
  return value;
}

function padded(spec: FieldSpec, value: unknown): unknown {
  if (spec.kind === "list" && Array.isArray(value)) {
    const items = value.map((item) => padded(spec.item, item));
    while (items.length < spec.low) items.push(items.length ? clone(items[items.length - 1]) : makeDefault(spec.item));
    return items;
  }
  if (spec.kind === "obj" && value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value as Fields).map(([key, item]) => [key, spec.fields[key] ? padded(spec.fields[key], item) : item]));
  }
  return value;
}

function makeDefault(spec: FieldSpec): unknown {
  if (spec.kind === "str") return "";
  if (spec.kind === "numbers") return [];
  if (spec.kind === "list") return Array.from({ length: spec.low }, () => makeDefault(spec.item));
  return Object.fromEntries(
    Object.entries(spec.fields)
      .filter(([, field]) => field.required)
      .map(([key, field]) => [key, makeDefault(field)]),
  );
}

function normalize(slide: DeckSlide): DeckSlide {
  if (slide.type === "roadmap" && Array.isArray(slide.periods) && Array.isArray(slide.lanes)) {
    const count = slide.periods.length;
    return { ...slide, lanes: (slide.lanes as Fields[]).map((lane) => ({ ...lane, cells: sized(asList(lane.cells), count, "") })) };
  }
  if (slide.type === "chart" && Array.isArray(slide.categories) && Array.isArray(slide.series)) {
    const count = slide.categories.length;
    return { ...slide, series: (slide.series as Fields[]).map((series) => ({ ...series, values: sized(asList(series.values), count, 0) })) };
  }
  return slide;
}

function sized<T>(list: T[], count: number, fill: T): T[] {
  return list.length >= count ? list.slice(0, count) : [...list, ...Array<T>(count - list.length).fill(fill)];
}

function asList<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function withKey(object: Fields, key: string, value: unknown): Fields {
  const next = { ...object };
  if (value === undefined) delete next[key];
  else next[key] = value;
  return next;
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function humanize(name: string) {
  const text = name.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
