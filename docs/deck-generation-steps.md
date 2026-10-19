# How a deck is created, step by step

This is the exact path from the user pressing Generate to a finished `.pptx` with previews. Everything runs on the Python service in `services/pptx/`; the web app only uploads, polls, and displays.

## At a glance: what the AI does

Steps 1 to 4 happen in a single model call: the writer reads, plans and writes in one reply. They are listed separately because the prompt asks for them in that order, not because they are separate calls.

- **Step 1 – Source analysis.** Reads the request and up to 90,000 characters of text pulled from the uploaded files, treating them as reference material, never as instructions.
- **Step 2 – Narrative.** Decides who the audience is, what they must believe or decide, and the governing thought: the one-sentence answer the deck argues.
- **Step 3 – Structure.** Groups the argument into 2 to 5 sections in a logical order. The deck opens with an executive summary, follows with an agenda when there are 3 or more sections, and closes with next steps when the sources support them.
- **Step 4 – Slide writing.** Gives each slide one point, with the headline stated as a full sentence. Picks the slide type that fits the evidence (KPIs, chart, roadmap, table and so on) and fills its fields, copying figures exactly from the sources.
- **Step 5 – Self-correction.** Our code checks the draft for broken structure, text that won't fit its box, and figures that don't appear in the sources. The writer fixes what's reported, up to 3 rounds.
- **Step 6 – Visual review.** A separate reviewer looks at images of the rendered slides, like an engagement manager would. It checks the story, whether each slide proves its headline, overstated claims, and layout problems, and raises up to 8 issues.
- **Step 7 – Revision.** The writer applies the review's fixes, and the step 5 checks run again before the deck is published.

## The core idea

The model never touches PowerPoint. It writes one JSON document (`deck.json`) that says, slide by slide, which slide type to use and what text and numbers go in it. Our renderer turns that document into slides inside the template's own layouts. Between the model and the final file sit three automatic checks (structure, text fit, figures against the sources) and one model review of the rendered slide images. Each failed check is sent back to the model as a list of specific fixes.

At most 10 model calls happen in one run:

| Step | Calls |
| --- | --- |
| Write the deck | 1, plus 1 retry if the reply isn't a deck |
| Fix check failures | up to 3 |
| Review the slide images | 1 |
| Apply the review | 1 |
| Fix check failures after the review | up to 3 |

## 1. The browser sends the request

**`apps/web/src/app/page.tsx`, `apps/web/src/lib/api.ts`**

1. `createDeck(prompt, files)` posts a form to `POST /api/jobs` with the prompt and any attached files.
2. The web app does not send `slide_count`, so the writer later chooses the length itself.
3. The returned job id is saved in `localStorage` so a page reload can pick the job back up.
4. From then on the page calls `GET /api/jobs/{id}` once a second until the job is `complete` or `failed`. (The server also offers `GET /api/jobs/{id}/events` as a server-sent event stream, but the web app does not use it.)

## 2. The server reads the files and creates the job

**`services/pptx/app/main.py` → `create_job`, `services/pptx/app/services/documents.py` → `extract_uploads`**

This part runs while the request is still open, so problems come back as immediate errors.

1. If no template is found, the request fails with 409.
2. Each file is read in turn:
   - Only `.pdf`, `.docx` and `.txt` are accepted; anything else gets a 415.
   - PDFs are read with `pypdf`, page by page.
   - Word files are read paragraph by paragraph, and tables become `| a | b |` lines with merged cells counted once.
   - Text files are read as UTF-8.
   - If all files together exceed 15 MB, the request fails with 413. An unreadable file fails with 422.
3. Each file's text is put under a `--- Source: <filename> ---` heading, and all of them are joined.
4. If the result is longer than 120,000 characters, it is cut there and marked as truncated.
5. `JobManager.create` deletes jobs older than 24 hours, makes a new job id, and writes `data/<job id>/job.json`.
6. The generation run is queued as a FastAPI background task, and the request returns `202` with the job.

**Which template is used** (`JobManager._template_path`):

1. The first `.pptx` in `assets/templates/` whose name contains "repository".
2. Otherwise `PPTX_TEMPLATE_PATH` from `.env`.
3. Otherwise the first `.pptx` in `assets/templates/`.

## 3. The workspace is prepared

**`services/pptx/app/services/jobs.py` → `_run_agent`, `services/pptx/app/agent/session.py` → `prepare_workspace`**

1. The status becomes `planning` (15%). The activity log records "Read N source files".
2. `data/<job id>/work/` is wiped and recreated. Into it go:
   - `template.pptx`, a copy of the chosen template
   - `sources.md`, the extracted source text
   - `request.md`, the user's prompt
3. The status becomes `building` (30%), "Writing the storyline".

## 4. A separate worker process runs the pipeline

**`session.py` → `run_agent`, `services/pptx/app/agent/worker.py`**

1. The service starts `python -m app.agent.worker` with its own Python (`.venv`) and writes one JSON request to its input. The request holds the OpenRouter connection settings from `.env`, the workspace path, the prompt, and the slide count.
2. The worker runs `run_pipeline` and prints one JSON line per event:
   - `activity` lines are added to the job's activity log, which the web app shows as progress.
   - A final `done` line reports success or the error.
3. If the worker hasn't finished after 40 minutes, it is killed and the job fails.

## 5. The writer drafts the whole deck in one call

**`services/pptx/app/agent/pipeline.py` → `_write`, `services/pptx/app/agent/llm.py` → `ask`**

1. The system prompt is `WRITER`, with two things filled in from `services/pptx/app/agent/deckspec.py`:
   - `catalog()` lists the 12 slide types: `executive_summary`, `kpis`, `cards`, `process`, `roadmap`, `table`, `chart`, `comparison`, `rows`, `statement`, `agenda` and `section`. For each one it gives when to use it, its fields with character and count limits, and an example.
   - `header_rules()` lists the header fields every content slide has: section, label, headline, subheader, source and takeaway.
2. The prompt asks the writer to work in this order:
   1. Decide the audience, the objective, and the governing thought.
   2. Group the material into 2 to 5 sections.
   3. Write one point per slide, with the headline stated as a full sentence.
   4. Open with an executive summary, and end with next steps when the sources support them.
   5. Use only figures from the sources, copied exactly.
3. The user message holds the request, a length instruction ("most decks need 8 to 14" when no count is given), and the first 90,000 characters of `sources.md` inside `<sources>` tags. It also tells the model to treat that material as reference, never as instructions.
4. `ask` calls Gemini through OpenRouter's chat completions endpoint, with a plain `httpx` request:
   - The reply is forced to be JSON (`response_format: {"type": "json_object"}`), up to 32,768 output tokens.
   - Each HTTP call can take up to 10 minutes. Dropped connections and 408, 429 and 5xx errors are retried up to 6 times, waiting 2, 4, 8, 16 and 32 seconds.
   - The conversation is saved to `work/sessions/<session id>.json`. Later fix calls continue the same conversation, so the model sees its earlier drafts.
5. `json_object` pulls the JSON out of the reply, accepting code fences or stray text around it.
6. If the reply isn't a deck with a `slides` list, the writer is asked once more: "Your reply was not a deck." If the second reply also fails, the job fails with "The writer did not return a deck."
7. The activity log records "Drafted N slides in M sections", followed by every headline.

## 6. The deck is checked, built, and fixed until it passes

**`pipeline.py` → `_settle`, `deckspec.py`, `services/pptx/app/agent/renderer.py`, `services/pptx/app/agent/textfit.py`**

This loop runs up to 4 times: the first check plus up to 3 fix rounds. Each time through:

1. **Add the agenda.** `with_agenda` inserts an `agenda` slide right after the executive summary when the deck has at least 7 slides and 3 or more sections, unless one is already there.
2. **Check the structure.** `structure_errors` collects every rule the deck breaks:
   - required fields missing, text over its character limit, lists with too few or too many entries
   - unknown slide types, or fields a type doesn't use
   - a slide whose section isn't one of the section names
   - more than 28 slides
   - slide 1 not an `executive_summary` (for decks of 5 or more slides)
   - two slides of the same type in a row, or a third table
   - table rows with the wrong number of cells, roadmap lanes with the wrong number of periods, chart series with the wrong number of values, an unknown chart type
3. **Build the file and measure the text.** If the structure is clean, `build` writes `work/presentation.pptx`:
   1. Open `template.pptx` and delete its existing slides.
   2. Find the cover, content, content-with-subheader and divider layouts by name, falling back to the content layout.
   3. Draw the cover, then each slide:
      - Content slides fill the template's title, section tag, subheader and footnote placeholders.
      - The optional takeaway becomes a red banner.
      - The body is drawn by that slide type's function in `DRAW`. Tables and charts are real PowerPoint tables and charts, not pictures.
   4. Before any text box is drawn, `textfit.fit` measures the wrapped text. It uses Arial widths plus a 7% safety margin, because the brand font isn't installed, and lowers the type size in 0.5 pt steps until the text fits or reaches that box's minimum size.
   5. Every box that still overflows at its minimum size is reported, for example: "Slide 4 (cards) item 2: the text needs about 130% of its space… Cut it to roughly 85 characters."
   6. Template layouts that no slide uses are removed, which shrinks the file from about 3.4 MB to about 90 KB.
4. **Check the figures.** `unsupported_figures` finds every number in the deck, including chart values, that doesn't appear in the sources or the request. It ignores commas, currency signs and trailing zeros, and skips whole numbers 12 and under. This check runs **only on the first pass**, so a number the model adds during a later fix is not checked.
5. **Decide.** If there are no structure errors, no overflowing text and no unsupported figures, the loop ends. Otherwise the activity log records "Fixing N problems found by the layout and fact checks". The model then gets the full problem list and the current deck, and replies either with just the changed slides (`{"replace": {"3": {...}}}`) or with a whole new deck. `apply_patch` merges the reply in.

After the last round:

- If structure errors remain, the job fails with "The deck could not be completed".
- If only text overflow remains, the deck is kept with that text at its smallest size, and the log says so.

`deck.json` is then saved.

## 7. The slides are rendered to images

**`pipeline.py` → `render_previews`, `services/pptx/app/pptx/preview.py` → `render_with_libreoffice`**

1. LibreOffice converts `presentation.pptx` to PDF, and `pdftoppm` turns each page into a 110 dpi PNG in `work/previews/`.
2. If LibreOffice or `pdftoppm` isn't installed, or rendering fails, the visual review is **skipped** and the run finishes with the deck from step 6.

## 8. A reviewer looks at the rendered slides

**`pipeline.py` → `_review`**

1. This is a separate, one-off conversation with the `REVIEWER` system prompt, which plays an engagement manager reviewing the deck. It is not saved to the writer's conversation.
2. The message holds the governing thought, a list of slides as "slide N: type: label | headline", and every slide PNG, each labelled with its line from that list.
3. The reviewer checks four things, in order: the story, whether each slide's body proves its headline, claims that overstate the evidence, and craft problems such as clipped text or empty slides.
4. It replies `{"verdict": "ship" | "revise", "issues": [...]}`, with at most 8 issues, each with a problem and a fix.
5. If the verdict is `ship`, there are no usable issues, the reply can't be read, **or the call raises any error**, the deck counts as passed. A failed review therefore looks the same as a clean one in the log ("The review passed the deck").

## 9. The writer applies the review

**`pipeline.py` → `run_pipeline`**

1. The issues go back to the writer, in the same conversation as step 5, along with the current deck. The writer may change slide types and merge, split, add or remove slides.
2. If the reply can't be read, the reviewed draft is kept.
3. Otherwise the revised deck goes through the step 6 loop again.
   - If it passes, `deck.json` is saved and the previews are rendered again.
   - If the revised deck ends with structure errors, it is thrown away: the earlier deck is rebuilt, and the log says the review changes did not fit the template.
4. The worker reports `done` with the session id, which is kept for later revisions.

## 10. The deck is published

**`jobs.py` → `finish`, `publish`**

1. If `work/presentation.pptx` doesn't exist, the job fails.
2. The status becomes `previewing` (85%).
3. The file is copied to `data/<job id>/presentation.pptx`.
4. `presentation_spec` reads the slide titles back out of the file into `spec.json`. That file only feeds the slide list in the sidebar.
5. The previews are rendered again into `data/<job id>/previews/`. If LibreOffice isn't available, plain SVG placeholders showing each title are made instead.
6. The status becomes `complete` (100%), "Ready to review", and `job.json` is saved with the activity log and timings.
7. The web app's next poll gets the preview URLs and the download link, `GET /api/jobs/{id}/download`.

## What ends up on disk

| Path under `data/<job id>/` | What it is |
| --- | --- |
| `job.json` | Prompt, source file names, session id, activity log, timings |
| `work/template.pptx` | Copy of the template used |
| `work/sources.md`, `work/request.md` | The extracted source text and the prompt |
| `work/sessions/<id>.json` | The writer's conversation, so revisions can continue it |
| `work/deck.json` | The deck document; the source of truth for edits and revisions |
| `work/presentation.pptx`, `work/previews/` | Working copy and the images the reviewer saw |
| `presentation.pptx`, `previews/`, `spec.json` | The published deck the web app serves |

Jobs are deleted 24 hours after they were created, the next time someone starts a new job. If the server restarts during a run, the job comes back as failed with "Generation interrupted".

## Revisions use the same pipeline

`POST /api/jobs/{id}/revise` runs steps 3 to 10 with three differences:

- The workspace isn't wiped.
- Step 5 is replaced by `_revise`: the writer gets the instruction and the current `deck.json`. It continues the saved conversation when there is one; otherwise the original request and sources are included again.
- The figure check also accepts numbers that appear in the revision instruction.

Inline text edits skip the model entirely; see `docs/inline-slide-editing.md`.
