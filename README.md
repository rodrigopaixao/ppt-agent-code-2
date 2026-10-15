# Template-driven PPTX chat

A local web application that uses a Claude model through OpenRouter to plan presentations, then renders them into an authorized PowerPoint template. Prompts and extracted document text are sent to OpenRouter; uploaded files, generated decks, and previews remain on this machine.

## Requirements

- Node.js 20+
- Python 3.9+
- An OpenRouter API key
- An authorized `.pptx` template with usable slide layouts
- Optional: LibreOffice and Poppler for pixel-accurate previews (the app falls back to local SVG previews)

## Start

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY to an OpenRouter key in .env
npm run setup
npm run template:demo # optional smoke-test template
npm run dev
```

Open http://localhost:3000. The API runs at http://localhost:8000.

Put the authorized template at `assets/templates/client-a-template.pptx`, or change `PPTX_TEMPLATE_PATH`. Template files and generated content are ignored by Git.

## Workflow

1. Enter a request and optionally attach PDF, DOCX, or TXT source files.
2. A Claude Agent SDK session, routed through OpenRouter, reads a catalogue of the template's example slides.
3. The agent edits those slides with `python-pptx`, including native tables and charts, renders the result, and fixes what it sees.
4. Review the thumbnails, ask for a revision in the same agent session, and download the editable `.pptx`.

The agent runtime uses Python 3.12 in `.venv312` because the Claude Agent SDK does not support the system Python. `npm run setup` creates it when `python3.12` is available. Install LibreOffice and Poppler if you want the agent to review real slide images rather than text previews.

## Data handling

The service extracts documents locally, but sends the prompt and extracted text to OpenRouter. It does not log document content. Jobs are stored under `data/` and are deleted automatically after 24 hours or when the service restarts. Do not use material that is not approved for the configured model provider.

## Template guidance

Use a clean template whose masters/layouts contain meaningful names and standard title/body placeholders. Existing example slides are removed from generated decks. Run:

```bash
PYTHONPATH=services/pptx .venv/bin/python -m app.pptx.inspector \
  --template assets/templates/client-a-template.pptx
```

The app searches every slide master and maps layout names to `title`, `section`, `title_content`, `two_column`, and `blank`. If the configured template path is missing, the single `.pptx` in `assets/templates/` is used. If automatic mapping is imperfect, add those terms to the layout names in PowerPoint's Slide Master view.
