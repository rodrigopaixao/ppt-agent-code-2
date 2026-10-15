import io
from pathlib import Path
from typing import List, Tuple

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(content: bytes) -> str:
    document = Document(io.BytesIO(content))
    lines: List[str] = []
    for block in document.element.body.iterchildren():
        if block.tag == qn("w:p"):
            lines.append(Paragraph(block, document).text)
        elif block.tag == qn("w:tbl"):
            lines.extend(_table_lines(Table(block, document)))
    return "\n".join(lines)


def _table_lines(table: Table) -> List[str]:
    lines = []
    for row in table.rows:
        cells = []
        seen = set()
        for cell in row.cells:
            # Merged cells are returned once per grid column.
            if cell._tc in seen:
                continue
            seen.add(cell._tc)
            cells.append(" ".join(cell.text.split()))
        lines.append("| " + " | ".join(cells) + " |")
    return lines + [""]


async def extract_uploads(
    uploads: List[UploadFile], max_bytes: int, max_chars: int
) -> Tuple[str, List[str]]:
    sections: List[str] = []
    names: List[str] = []
    total_bytes = 0
    for upload in uploads:
        name = Path(upload.filename or "document").name
        extension = Path(name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {extension or 'unknown'}")
        content = await upload.read()
        total_bytes += len(content)
        if total_bytes > max_bytes:
            raise HTTPException(status_code=413, detail="Uploaded files exceed the size limit.")
        try:
            if extension == ".pdf":
                text = extract_pdf(content)
            elif extension == ".docx":
                text = extract_docx(content)
            else:
                text = content.decode("utf-8")
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Could not read {name}.") from error
        sections.append(f"--- Source: {name} ---\n{text.strip()}")
        names.append(name)
    combined = "\n\n".join(sections)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[Source text truncated at local safety limit.]"
    return combined, names
