# Click-to-edit text on slide previews

Users click any piece of text on a slide preview and type over it in place, like in PowerPoint. When they finish, the deck is rebuilt and the preview refreshes about 5 seconds later.

## The core idea

The browser never edits the PowerPoint file. The slide preview is a PNG image, and every slide is drawn from a JSON document (`deck.json`) by our renderer. So editing works in three steps:

1. **When the renderer draws text, it also records where it drew it.** It notes the box position, the text style, and which field in `deck.json` the text came from. We call each of these records a *region*.
2. **The browser lays invisible click targets over the image, one per region.** Clicking one opens an editable box in exactly that spot, styled to match the slide.
3. **On save, the browser writes the new text into `deck.json` at the recorded field and sends the whole deck back.** The server rebuilds the `.pptx` and re-renders the previews.

Because edits go into the deck document rather than the file, the renderer's layout rules (text fitting, house style) still apply to every edit.

## What a region looks like

Positions are in inches on a 13.333 × 7.5 slide. Slide 0 is the cover.

```json
{
  "slide": 5,
  "box": [0.78, 4.12, 2.6, 2.1],
  "inset": [0.05, 0.05, 0.03, 0.03],
  "anchor": "t",
  "fill": "F5EFE8",
  "title": null,
  "items": { "path": ["slides", 4, "items", 0, "points"], "start": 0, "end": 3, "low": 1, "high": 4 },
  "paras": [
    {
      "path": ["slides", 4, "items", 0, "points", 0],
      "also": [],
      "text": "First bullet text",
      "size": 13, "bold": false, "color": "000000", "accent": "",
      "align": "l", "bullet": true, "space_before": 6, "caps": false, "spacing": 0
    }
  ]
}
```

- `paras[].path` is the field in `deck.json` that each paragraph comes from.
- `also` lists extra fields that receive the same value. For example, a roadmap bar spanning three periods is stored as three identical cells.
- `items` is set for bullet lists. It says which slice of the list this box shows and the allowed number of bullets, so Enter and Backspace can add and remove bullets within the limits.
- `title` is set for slide titles, which show two fields as "Label | Headline". It carries both paths plus the label colour.
- `fill` is the background colour behind the text. It is found automatically from the shape drawn underneath the text box.

## Backend (Python)

**`services/pptx/app/agent/renderer.py`**
- `build(template, deck, dest, regions=None)`: pass a list and it is filled with regions.
- The drawing helpers `Canvas.text(...)` and `Canvas.text_in(...)` take an `edit=` argument that says which deck field the text came from. Helpers build it:
  - `c.at("items", 0, "heading")` for a single field
  - `c.fields(...)` for one box showing several fields
  - `c.items(("items", 0, "points"), indices)` for bullet lists
- Template placeholders (titles, cover, footnote, subheader) are recorded with `canvas.placeholder(...)`.
- Native tables are recorded cell by cell from the column widths and row heights the renderer already calculates.
- Not editable on the slide: chart numbers, slide numbers, the section tag, and card or step numbers.

**`services/pptx/app/services/jobs.py`**
- `regions(job)` returns the cached `regions.json`, or rebuilds it with a throwaway build (about 1 second) if `deck.json` is newer. This is why older decks work without regenerating.
- `save_deck(job, deck)` rebuilds the presentation into a temporary file and swaps it in, then writes `deck.json` and `regions.json`. A lock stops two saves from interleaving.
- `render_edit(job)` re-renders the previews. If more edits arrive while it runs, it loops until it has rendered the latest one, and only then reports "complete".

**`services/pptx/app/main.py`**
- `GET /api/jobs/{id}/deck` returns `{deck, schema, regions}`.
- `PUT /api/jobs/{id}/deck` with body `{deck}` validates the deck and returns `{job, warnings, regions}`. Validation failures return 422 with the specific errors.
- Saves are allowed while previews are refreshing, but blocked while an AI generation run is in progress.

## Frontend (Next.js)

All of this is in **`apps/web/src/components/slide-stage.tsx`**.

**`useInlineEditing(job, ...)` hook**
- Loads the deck and regions.
- Applies each edit to its local copy of the deck straight away, then saves it to the server.
- Keeps an undo history of up to 50 steps, available through ⌘Z or the Undo button.
- If a save fails, it reverts and shows the error.

**`SlideStage` component**
- Draws the preview image, then one transparent button per region on top of it. Positions are percentages of the slide, so they scale with the image.
- Hovering a button shows a dashed outline.
- If the user clicks while a save is still running, the click is remembered and the box opens once the save finishes.

**`InlineBox` component (the editor)**
- Each paragraph is its own `contentEditable` div, with font size, colour, alignment, bullets and spacing taken from the region.
- Points are converted to pixels as `size / 72 × (image width / 13.333)`.
- The caret lands where the user clicked, using `caretRangeFromPoint`.
- Keys:
  - **Enter** splits the bullet at the caret, or saves if the box isn't a list.
  - **Backspace** at the start of a bullet joins it to the bullet above.
  - **Tab** moves to the next field.
  - **Esc** cancels.
  - **Clicking outside** saves.
- Bold is stored as `**markdown**` in the deck. It is shown as `<b>`, and ⌘B toggles it.
- Pasted text is inserted as plain text.

**`applyEdit(deck, region, texts)`**
- Writes the edited text back into the deck.
- Clearing an optional field removes it from the deck.
- Renaming a section also updates every slide that uses that section.

**Bridging the refresh gap.** After saving, the edited text stays drawn over the old image until the new preview arrives, so the user never sees the old text come back.

## Prerequisite that made this fast enough

Previews used to take about 20 seconds because every output file carried all 150+ layouts from the template. `_remove_unused_layouts()` in the renderer now drops any layout no slide uses before saving:

- the file shrinks from 3.4 MB to about 90 KB
- a full preview render takes about 3.5 seconds instead of 20
- the rendered slides are pixel-identical

Without this, in-place editing would feel broken.

## Known limits

- Fields that are currently empty, such as a missing cover subtitle, aren't drawn on the slide, so they can't be clicked. Use the "Edit slides" panel for those, and for anything structural: adding or removing slides, changing slide types, and chart data.
- The edit box uses Arial while the previews use LibreOffice's substitute for the brand font, so line breaks while typing can differ slightly from the final render.
- While typing, text can overflow its box; the renderer shrinks it to fit on save. If it can't fit even at the smallest allowed size, the user gets a warning naming the slide.

## Tests

- `services/pptx/tests/test_editing.py` checks three things:
  - every region's field path resolves to the text it shows
  - edits saved during a refresh are accepted and rendered
  - invalid edits are rejected
- The browser was checked with Playwright (`data/_render/ui/inline_shot.py`, `inline_types.py`). The scripts cover title edits, adding a bullet, undo, clicking during a save, the error path, and the cover, KPI, table and roadmap slides.
