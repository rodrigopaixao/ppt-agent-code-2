# Template-driven PPTX chat

A local web application that uses Google Gemini, through OpenRouter, to plan and write presentations, then renders them into an authorized PowerPoint template. Prompts, extracted document text, and rendered slide images are sent to OpenRouter; uploaded files, generated decks, and previews remain on this machine.

## Requirements

- Node.js 20+
- Python 3.9+
- An OpenRouter API key
- An authorized `.pptx` template with usable slide layouts
- Optional: LibreOffice and Poppler for pixel-accurate previews (the app falls back to local SVG previews)

## Start

```bash
cp .env.example .env
# Set OPENROUTER_API_KEY in .env (OPENROUTER_MODEL defaults to google/gemini-3.8-flash)
npm run setup
npm run template:demo # optional smoke-test template
npm run dev
```

Open http://localhost:3000. The API runs at http://localhost:8000.

Put the authorized template at `assets/templates/client-a-template.pptx`, or change `PPTX_TEMPLATE_PATH`. Template files and generated content are ignored by Git.

## Workflow

1. Enter a request and optionally attach PDF, DOCX, or TXT source files.
2. Gemini plans the storyline and writes the whole deck as JSON, choosing a slide type for each point.
3. The renderer draws each slide in the template's masters. Layout and fact checks send problems back to Gemini to fix.
4. The slides are rendered to images and Gemini reviews them as an engagement manager would, then the writer applies the fixes.
5. Review the slides, edit text in place or in the edit panel, ask for a revision (which continues the same conversation), and download the editable `.pptx`.

The pipeline runs in a separate Python process and calls OpenRouter's chat completions API directly. Conversations are kept in each job's `work/sessions/` folder so revisions can continue them. Install LibreOffice and Poppler so the review step can see real slide images.

## Data handling

The service extracts documents locally, but sends the prompt, extracted text, and rendered slide images to OpenRouter, which forwards them to Google. It does not log document content. Jobs are stored under `data/` and are deleted automatically after 24 hours or when the service restarts. Do not use material that is not approved for the configured model provider.

## Template guidance

Use a clean template whose masters/layouts contain meaningful names and standard title/body placeholders. Existing example slides are removed from generated decks. Run:

```bash
PYTHONPATH=services/pptx .venv/bin/python -m app.pptx.inspector \
  --template assets/templates/client-a-template.pptx
```

The app searches every slide master and maps layout names to `title`, `section`, `title_content`, `two_column`, and `blank`. If the configured template path is missing, the single `.pptx` in `assets/templates/` is used. If automatic mapping is imperfect, add those terms to the layout names in PowerPoint's Slide Master view.
