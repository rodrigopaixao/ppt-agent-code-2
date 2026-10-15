from pathlib import Path
from typing import Iterable, List, Optional

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.util import Emu, Inches, Pt

from app.models.presentation import ContentBlock, LayoutName, PresentationSpec, SlideSpec
from app.pptx.inspector import map_layouts


TITLE_TYPES = (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
BODY_TYPES = (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.SUBTITLE)


def remove_existing_slides(presentation: Presentation) -> None:
    slide_ids = list(presentation.slides._sldIdLst)  # noqa: SLF001
    for slide_id in slide_ids:
        relationship_id = slide_id.rId
        presentation.part.drop_rel(relationship_id)
        presentation.slides._sldIdLst.remove(slide_id)  # noqa: SLF001


def block_lines(block: ContentBlock) -> List[str]:
    lines: List[str] = []
    if block.heading:
        lines.append(block.heading)
    if block.text:
        lines.append(block.text)
    lines.extend(block.items)
    return lines


def all_lines(blocks: Iterable[ContentBlock]) -> List[str]:
    lines: List[str] = []
    for block in blocks:
        lines.extend(block_lines(block))
    return lines


def set_text(shape, lines: List[str], *, bullets: bool = True) -> None:
    text_frame = shape.text_frame
    text_frame.clear()
    text_frame.word_wrap = True
    for index, line in enumerate(lines or [""]):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        paragraph.text = line
        paragraph.level = 0
        if bullets and index > 0:
            paragraph.level = 0


def placeholders_by_type(slide, types) -> List:
    return [
        shape
        for shape in slide.placeholders
        if shape.placeholder_format.type in types and hasattr(shape, "text_frame")
    ]


def _inches(value: Optional[Emu]) -> float:
    return value.inches if value is not None else 0


def body_shapes(slide, *, minimum_inches: float) -> List:
    shapes = [
        shape
        for shape in placeholders_by_type(slide, BODY_TYPES)
        if _inches(shape.height) >= minimum_inches
    ]
    return sorted(shapes, key=lambda shape: (-_inches(shape.height), shape.left, shape.top))


def fill_slide(slide, spec: SlideSpec) -> None:
    title_shapes = placeholders_by_type(slide, TITLE_TYPES)
    if title_shapes:
        title_shapes[0].text = spec.title
    else:
        box = slide.shapes.add_textbox(Inches(0.7), Inches(0.45), Inches(11.9), Inches(0.7))
        box.text_frame.text = spec.title
        box.text_frame.paragraphs[0].font.size = Pt(28)
        box.text_frame.paragraphs[0].font.bold = True

    if spec.layout in (LayoutName.TITLE, LayoutName.SECTION):
        lines = [spec.subtitle] if spec.subtitle else all_lines(spec.blocks)
        labels = body_shapes(slide, minimum_inches=0.3)
        if labels:
            set_text(labels[0], lines, bullets=False)
        return

    columns = body_shapes(slide, minimum_inches=1)
    lines = all_lines(spec.blocks)
    if spec.subtitle:
        lines.insert(0, spec.subtitle)
    if spec.layout == LayoutName.TWO_COLUMN and len(columns) >= 2:
        ordered = sorted(columns, key=lambda shape: shape.left)
        midpoint = max(1, (len(spec.blocks) + 1) // 2)
        set_text(ordered[0], all_lines(spec.blocks[:midpoint]))
        set_text(ordered[1], all_lines(spec.blocks[midpoint:]))
    elif columns:
        set_text(max(columns, key=lambda shape: _inches(shape.width) * _inches(shape.height)), lines)
    elif lines:
        box = slide.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(11.6), Inches(5.3))
        set_text(box, lines)
        for paragraph in box.text_frame.paragraphs:
            paragraph.font.size = Pt(20)
            paragraph.space_after = Pt(10)

    notes = spec.speaker_notes or ""
    if spec.sources:
        notes += ("\n\n" if notes else "") + "Sources:\n" + "\n".join(spec.sources)
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def build_presentation(template_path: Path, spec: PresentationSpec, output_path: Path) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found at {template_path}. Add an authorized template or run the demo template command."
        )
    presentation = Presentation(str(template_path))
    mapping = map_layouts(presentation)
    remove_existing_slides(presentation)
    for slide_spec in spec.slides:
        choice = mapping[slide_spec.layout]
        layout = presentation.slide_masters[choice.master_index].slide_layouts[choice.layout_index]
        slide = presentation.slides.add_slide(layout)
        fill_slide(slide, slide_spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(str(output_path))
    return output_path
