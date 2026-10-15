import io

from docx import Document

from app.services.documents import extract_docx


def test_docx_tables_are_extracted_in_document_order() -> None:
    document = Document()
    document.add_paragraph("5. Task list")
    table = document.add_table(rows=3, cols=3)
    for cell, text in zip(table.rows[0].cells, ["ID", "Task", "Duration"]):
        cell.text = text
    phase = table.rows[1].cells[0].merge(table.rows[1].cells[2])
    phase.text = "Phase 1: Discovery"
    for cell, text in zip(table.rows[2].cells, ["1", "Project kickoff", "1 day"]):
        cell.text = text
    document.add_paragraph("6. Key milestones")
    buffer = io.BytesIO()
    document.save(buffer)

    lines = extract_docx(buffer.getvalue()).splitlines()

    assert lines[:4] == [
        "5. Task list",
        "| ID | Task | Duration |",
        "| Phase 1: Discovery |",
        "| 1 | Project kickoff | 1 day |",
    ]
    assert "6. Key milestones" in lines[4:]
