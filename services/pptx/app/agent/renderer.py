"""Draw a deck document into the template's own masters using a fixed set of components."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE, PP_PLACEHOLDER
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.agent.deckspec import TYPES, parse_day, section_number
from app.agent.textfit import BULLET_INDENT, Para, block_height, fit, line_count, plain, runs, shrink, text_width, wrap

RED = "EC111A"
DARK_RED = "B10D13"
TAN = "F5EFE8"
TAN_DARK = "E5D7C5"
STONE = "D8D6CA"
STONE_DARK = "BCB8A4"
DEEP_RED = "C00000"
LIGHT_GREY = "F6F6F6"
BAND_GREY = "F2F2F2"
REVIEW_GREY = "D9D9D9"
MILESTONE_GREEN = "00B050"
DATE_BLUE = "0070C0"
SUBMISSION_TAN = "D7C0A3"
SUBMISSION_BROWN = "805F38"
GREY = "595959"
BLACK = "000000"
WHITE = "FFFFFF"
SERIES_COLORS = (RED, STONE_DARK, GREY)

LAYOUT_NAMES = {
    "cover": ("Cover_Red", "Board Cover Slide", "Cover_Tan"),
    "content": ("BoardContent", "1_BoardContent", "2_BoardContent"),
    "content_sub": ("BoardContent_Sub", "1_BoardContent_Sub", "2_BoardContent_Sub"),
    "divider": ("Divider_Tan", "Divider_White", "Divider_Red"),
}

X0 = 0.56
WIDTH = 12.2
RIGHT = X0 + WIDTH
TOP = 1.86
TOP_SUB = 2.24
BOTTOM = 6.7
BANNER = 0.5
NO_STYLE_TABLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"
ANCHORS = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}
ALIGNS = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
PLACEHOLDER_INSET = (0.1, 0.1, 0.05, 0.05)


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class Edit:
    """Where each drawn paragraph comes from in the deck document, so the text can be edited in place."""

    paths: List[tuple]
    also: Optional[List[List[tuple]]] = None
    items: Optional[dict] = None
    title: Optional[dict] = None


class Canvas:
    def __init__(
        self,
        slide,
        number: int,
        kind: str,
        problems: List[str],
        regions: Optional[List[dict]] = None,
        base: tuple = (),
        background: str = WHITE,
    ):
        self.slide = slide
        self.number = number
        self.kind = kind
        self.problems = problems
        self.regions = regions
        self.base = base
        self.background = background
        self.fills: List[Tuple[Box, str]] = []

    def at(self, *keys) -> Edit:
        return Edit([self.base + keys])

    def fields(self, *paths: tuple) -> Edit:
        return Edit([self.base + path for path in paths])

    def items(self, keys: tuple, indices: Sequence[int]) -> Edit:
        spec = {"kind": "obj", "fields": TYPES[self.kind]["fields"]}
        for key in keys:
            spec = spec["item"] if isinstance(key, int) else spec["fields"][key]
        start, end = (indices[0], indices[-1] + 1) if indices else (0, 0)
        return Edit(
            [self.base + keys + (index,) for index in indices],
            items={"path": list(self.base + keys), "start": start, "end": end, "low": spec["low"], "high": spec["high"]},
        )

    def record(
        self,
        box: Box,
        paras: Sequence[Para],
        edit: Optional[Edit],
        inset: Tuple[float, float, float, float],
        anchor: str,
    ) -> None:
        if self.regions is None or edit is None or not paras:
            return
        x, y = box.x + box.w / 2, box.y + box.h / 2
        fill = next(
            (color for area, color in reversed(self.fills) if area.x <= x <= area.right and area.y <= y <= area.bottom),
            self.background,
        )
        also = edit.also or [[] for _ in edit.paths]
        self.regions.append(
            {
                "slide": self.number,
                "box": [round(value, 4) for value in (box.x, box.y, box.w, box.h)],
                "inset": [round(value, 4) for value in inset],
                "anchor": anchor,
                "fill": fill,
                "title": edit.title,
                "items": edit.items,
                "paras": [
                    {
                        "path": list(path),
                        "also": [list(other) for other in extra],
                        "text": para.text,
                        "size": round(para.size, 2),
                        "bold": para.bold,
                        "color": para.color,
                        "accent": para.accent,
                        "align": para.align,
                        "bullet": para.bullet,
                        "space_before": round(para.space_before, 2),
                        "caps": para.caps,
                        "spacing": para.spacing,
                        "italic": para.italic,
                    }
                    for para, path, extra in zip(paras, edit.paths, also)
                ],
            }
        )

    def placeholder(self, shape, paras: Sequence[Para], edit: Edit, anchor: str, inset=PLACEHOLDER_INSET) -> None:
        box = Box(shape.left.inches, shape.top.inches, shape.width.inches, shape.height.inches)
        self.record(box, paras, edit, inset, anchor)

    def problem(self, where: str, paras: Sequence[Para], ratio: float) -> None:
        characters = sum(len(plain(para.text)) for para in paras)
        target = max(10, int(characters / max(ratio, 1.01) * 0.9))
        self.problems.append(
            f"Slide {self.number} ({self.kind}) {where}: the text needs about {ratio:.0%} of its space at the "
            f"smallest type size. Cut it to roughly {target} characters."
        )

    def uniform(self, groups: Sequence[Tuple[Sequence[Para], float, float, str]], floor: float) -> float:
        results = [fit(paras, width, height, floor) for paras, width, height, _where in groups]
        for (paras, _width, _height, where), result in zip(groups, results):
            if not result.ok:
                self.problem(where, paras, result.ratio)
        return max((result.shrink for result in results), default=0.0)

    def rect(self, box: Box, fill: Optional[str], line: Optional[str] = None, shape=MSO_SHAPE.RECTANGLE, line_width: float = 0.75):
        item = self.slide.shapes.add_shape(shape, Inches(box.x), Inches(box.y), Inches(box.w), Inches(box.h))
        item.shadow.inherit = False
        if fill:
            self.fills.append((box, fill))
            item.fill.solid()
            item.fill.fore_color.rgb = RGBColor.from_string(fill)
        else:
            item.fill.background()
        if line:
            item.line.color.rgb = RGBColor.from_string(line)
            item.line.width = Pt(line_width)
        else:
            item.line.fill.background()
        return item

    def line(
        self, x1: float, y1: float, x2: float, y2: float, color: str = STONE, width: float = 0.75, dash: Union[bool, str] = False
    ) -> None:
        connector = self.slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
        connector.line.color.rgb = RGBColor.from_string(color)
        connector.line.width = Pt(width)
        if dash:
            line_props = connector.line._get_or_add_ln()  # noqa: SLF001
            dash_node = etree.SubElement(line_props, qn("a:prstDash"))
            dash_node.set("val", dash if isinstance(dash, str) else "sysDash")

    def text(
        self,
        box: Box,
        paras: Sequence[Para],
        where: str = "",
        floor: float = 9.0,
        anchor: str = "t",
        amount: Optional[float] = None,
        inset: Tuple[float, float] = (0.05, 0.03),
        max_lines: Optional[int] = None,
        edit: Optional[Edit] = None,
    ):
        if amount is None:
            result = fit(paras, box.w - 2 * inset[0], box.h - 2 * inset[1], floor, max_lines)
            if not result.ok and where:
                self.problem(where, paras, result.ratio)
            amount = result.shrink
        shape = self.slide.shapes.add_textbox(Inches(box.x), Inches(box.y), Inches(box.w), Inches(box.h))
        drawn = shrink(paras, amount, floor)
        write(shape.text_frame, drawn, inset, anchor)
        self.record(box, drawn, edit, (inset[0], inset[0], inset[1], inset[1]), anchor)
        return shape

    def text_in(
        self,
        shape,
        paras: Sequence[Para],
        amount: float,
        floor: float,
        inset: Tuple[float, float, float, float],
        anchor: str = "m",
        edit: Optional[Edit] = None,
    ) -> None:
        frame = shape.text_frame
        drawn = shrink(paras, amount, floor)
        write(frame, drawn, (0.0, 0.0), anchor)
        frame.margin_left, frame.margin_right = Inches(inset[0]), Inches(inset[1])
        frame.margin_top, frame.margin_bottom = Inches(inset[2]), Inches(inset[3])
        box = Box(shape.left.inches, shape.top.inches, shape.width.inches, shape.height.inches)
        self.record(box, drawn, edit, inset, anchor)


def write(frame, paras: Sequence[Para], inset: Tuple[float, float], anchor: str) -> None:
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.NONE
    frame.margin_left = frame.margin_right = Inches(inset[0])
    frame.margin_top = frame.margin_bottom = Inches(inset[1])
    frame.vertical_anchor = ANCHORS[anchor]
    write_paragraphs(frame, paras)


def write_paragraphs(frame, paras: Sequence[Para]) -> None:
    for index, spec in enumerate(paras):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        for run in list(paragraph.runs):
            run._r.getparent().remove(run._r)  # noqa: SLF001
        paragraph.alignment = ALIGNS[spec.align]
        if index and spec.space_before:
            paragraph.space_before = Pt(spec.space_before)
        properties = paragraph._p.get_or_add_pPr()  # noqa: SLF001
        if spec.bullet:
            indent = int(Inches(BULLET_INDENT))
            properties.set("marL", str(indent))
            properties.set("indent", str(-indent))
            font = etree.SubElement(properties, qn("a:buFont"))
            font.set("typeface", "Arial")
            char = etree.SubElement(properties, qn("a:buChar"))
            char.set("char", "•")
        else:
            properties.set("marL", "0")
            properties.set("indent", "0")
            etree.SubElement(properties, qn("a:buNone"))
        for text, bold in runs(spec.text) or [("", False)]:
            run = paragraph.add_run()
            run.text = text.upper() if spec.caps else text
            run.font.size = Pt(spec.size)
            run.font.bold = spec.bold or bold
            if spec.italic:
                run.font.italic = True
            color = spec.accent if (bold and spec.accent) else spec.color
            run.font.color.rgb = RGBColor.from_string(color)
            if spec.spacing:
                run._r.get_or_add_rPr().set("spc", str(spec.spacing))  # noqa: SLF001


def build(template: Path, deck: dict, destination: Path, regions: Optional[List[dict]] = None) -> List[str]:
    """Render the deck. Returns layout problems (text that cannot fit) for the writer to fix.

    When ``regions`` is given, it is filled with the position, style and deck path of every editable text box.
    """
    presentation = Presentation(str(template))
    _remove_all_slides(presentation)
    layouts = _layouts(presentation)
    problems: List[str] = []
    _cover(presentation, layouts, deck.get("cover") or {}, problems, regions)
    for number, slide in enumerate(deck.get("slides") or [], start=1):
        kind = slide.get("type")
        if kind == "section":
            _divider(presentation, layouts, deck, slide, number, problems, regions)
            continue
        if kind == "agenda":
            slide = dict(slide)
            slide.setdefault("label", "Agenda")
            slide["headline"] = slide.get("headline") or "What we will cover"
            slide["section"] = slide.get("section") or "Agenda"
        canvas, body = _content_slide(presentation, layouts, slide, number, kind, problems, regions)
        DRAW[kind](canvas, slide, body, deck)
    _remove_unused_layouts(presentation)
    presentation.save(str(destination))
    return problems


def _remove_all_slides(presentation) -> None:
    slide_ids = presentation.slides._sldIdLst  # noqa: SLF001
    for slide_id in list(slide_ids):
        presentation.part.drop_rel(slide_id.rId)
        slide_ids.remove(slide_id)


def _remove_unused_layouts(presentation) -> None:
    """Drop template layouts and masters no slide uses; they make the file large and slow to render."""
    used = {slide.slide_layout.part.partname for slide in presentation.slides}
    for master in presentation.slide_masters:
        layout_ids = master._element.get_or_add_sldLayoutIdLst()  # noqa: SLF001
        for entry in list(layout_ids):
            if master.part.related_part(entry.rId).partname not in used:
                master.part.drop_rel(entry.rId)
                layout_ids.remove(entry)
    master_ids = presentation.part._element.get_or_add_sldMasterIdLst()  # noqa: SLF001
    for entry in list(master_ids):
        master = presentation.part.related_part(entry.rId).slide_master
        if not len(master.slide_layouts):
            presentation.part.drop_rel(entry.rId)
            master_ids.remove(entry)


def _layouts(presentation) -> Dict[str, object]:
    found: Dict[str, object] = {}
    for role, names in LAYOUT_NAMES.items():
        for name in names:
            for master in presentation.slide_masters:
                match = next((layout for layout in master.slide_layouts if layout.name == name), None)
                if match is not None:
                    found[role] = match
                    break
            if role in found:
                break
    fallback = presentation.slide_layouts[0]
    for role in LAYOUT_NAMES:
        found.setdefault(role, found.get("content", fallback))
    return found


def _placeholder(slide, idx: int):
    for shape in slide.placeholders:
        if shape.placeholder_format.idx == idx:
            return shape
    return None


def _remove(shape) -> None:
    if shape is not None:
        shape._element.getparent().remove(shape._element)  # noqa: SLF001


def _set_runs(shape, pieces: Sequence[Tuple[str, Optional[str], Optional[float]]]) -> None:
    frame = shape.text_frame
    paragraph = frame.paragraphs[0]
    for extra in frame.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)  # noqa: SLF001
    for run in list(paragraph.runs):
        run._r.getparent().remove(run._r)  # noqa: SLF001
    for text, color, size in pieces:
        run = paragraph.add_run()
        run.text = text
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        if size:
            run.font.size = Pt(size)


def _slide_number(slide, layout) -> None:
    for shape in layout.placeholders:
        if shape.placeholder_format.type == PP_PLACEHOLDER.SLIDE_NUMBER:
            slide.shapes._spTree.append(deepcopy(shape._element))  # noqa: SLF001
            return


def _cover(presentation, layouts, cover: dict, problems: List[str], regions: Optional[List[dict]]) -> None:
    layout = layouts["cover"]
    slide = presentation.slides.add_slide(layout)
    canvas = Canvas(slide, 0, "cover", problems, regions, ("cover",), RED)
    title = str(cover.get("title") or "")
    title_box = _placeholder(slide, 10) or slide.shapes.title
    if title_box is not None:
        width = title_box.width.inches - 0.2
        result = fit([Para(title, 60, bold=True)], width, 99, 36, max_lines=2)
        size = 60 - result.shrink
        lines = line_count(Para(title, size, bold=True), width)
        if lines > 2:
            problems.append(f"Cover title: shorten it to about {int(len(title) * 2 / lines)} characters.")
        needed = lines * size * 1.2 / 72 + 0.15
        left, top, box_width, height = (title_box.left, title_box.top, title_box.width, title_box.height)
        bottom = top.inches + height.inches
        grown = max(needed, height.inches)
        title_box.left, title_box.width = left, box_width
        title_box.top, title_box.height = Inches(bottom - grown), Inches(grown)
        _set_runs(title_box, [(title, None, size)])
        canvas.placeholder(title_box, [Para(title, size, bold=True, color=WHITE)], canvas.at("title"), "b", (0, 0, 0, 0))
    for idx, key, size in ((11, "subtitle", 16), (12, "date", 14)):
        shape = _placeholder(slide, idx)
        value = str(cover.get(key) or "")
        if shape is None:
            continue
        if value:
            _set_runs(shape, [(value, None, None)])
            canvas.placeholder(shape, [Para(value, size, color=WHITE)], canvas.at(key), "m")
        else:
            _remove(shape)


def _divider(
    presentation, layouts, deck: dict, slide_data: dict, number: int, problems: List[str], regions: Optional[List[dict]]
) -> None:
    layout = layouts["divider"]
    slide = presentation.slides.add_slide(layout)
    canvas = Canvas(slide, number, "section", problems, regions, background=TAN)
    name = str(slide_data.get("section") or "")
    number_box = _placeholder(slide, 12)
    if number_box is not None:
        _set_runs(number_box, [(f"{section_number(deck, name):02d}", None, None)])
    title_box = _placeholder(slide, 11)
    if title_box is not None:
        width = title_box.width.inches - 0.2
        result = fit([Para(name, 66)], width, 99, 40, max_lines=2)
        if not result.ok:
            problems.append(f"Slide {number} (section): shorten the section name.")
        _set_runs(title_box, [(name, None, 66 - result.shrink)])
        index = next((i for i, section in enumerate(deck.get("sections") or []) if isinstance(section, dict) and section.get("name") == name), None)
        if index is not None:
            canvas.placeholder(title_box, [Para(name, 66 - result.shrink)], Edit([("sections", index, "name")]), "t")
    _slide_number(slide, layout)


def _content_slide(
    presentation, layouts, data: dict, number: int, kind: str, problems: List[str], regions: Optional[List[dict]]
) -> Tuple[Canvas, Box]:
    subheader = str(data.get("subheader") or "").strip()
    layout = layouts["content_sub"] if subheader else layouts["content"]
    slide = presentation.slides.add_slide(layout)
    canvas = Canvas(slide, number, kind, problems, regions, ("slides", number - 1))

    label = str(data.get("label") or "").strip()
    headline = plain(str(data.get("headline") or "").strip())
    title = slide.shapes.title
    if title is not None:
        lead = f"{label} | " if label else ""
        result = fit([Para(lead + headline, 22)], title.width.inches - 0.2, 99, 18, max_lines=2)
        if not result.ok:
            canvas.problem("label and headline", [Para(lead + headline, 22)], 1.3)
        size = 22 - result.shrink if result.shrink else None
        pieces = [(lead, RED, size)] if lead else []
        pieces.append((headline, None, size))
        _set_runs(title, pieces)
        edit = canvas.at("headline")
        edit.title = {"label": list(canvas.base + ("label",)), "headline": list(canvas.base + ("headline",)), "accent": RED}
        canvas.placeholder(title, [Para(lead + headline, size or 22)], edit, "t")

    tag = _placeholder(slide, 13)
    section = str(data.get("section") or "").strip()
    if tag is not None:
        if section:
            _set_runs(tag, [(section.upper(), None, None)])
        else:
            _remove(tag)

    for shape in list(slide.placeholders):
        idx = shape.placeholder_format.idx
        if shape.placeholder_format.type in (PP_PLACEHOLDER.OBJECT,) or idx == 12:
            _remove(shape)
        elif subheader and idx in (14, 15) and shape.top.inches > 1.5:
            _set_runs(shape, [(subheader.upper(), None, None)])
            canvas.placeholder(shape, [Para(subheader, 9, caps=True, spacing=200)], canvas.at("subheader"), "m")

    bottom = BOTTOM
    source = str(data.get("source") or "").strip()
    footnote = _placeholder(slide, 11)
    if footnote is not None:
        if source:
            width = footnote.width.inches - 0.1
            result = fit([Para(source, 9)], width, 99, 7.5, max_lines=2)
            size = 9 - result.shrink
            lines = line_count(Para(source, size), width)
            if lines > 2:
                canvas.problem("source", [Para(source, 9)], lines / 2)
            _set_runs(footnote, [(source, None, size if result.shrink else None)])
            canvas.placeholder(footnote, [Para(source, size)], canvas.at("source"), "b")
            bottom = min(bottom, 7.07 - lines * size * 1.2 / 72 - 0.12)
        else:
            _remove(footnote)
    _slide_number(slide, layout)

    top = TOP_SUB if subheader else TOP
    takeaway = str(data.get("takeaway") or "").strip()
    if takeaway and kind not in {"agenda", "statement"}:
        banner = Box(X0, bottom - BANNER, WIDTH, BANNER)
        canvas.rect(banner, RED)
        canvas.text(
            banner, [Para(takeaway, 14, color=WHITE, align="c")], "takeaway", floor=11, anchor="m", inset=(0.3, 0.04),
            edit=canvas.at("takeaway"),
        )
        bottom = banner.y - 0.2
    return canvas, Box(X0, top, WIDTH, bottom - top)


def _executive_summary(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    items = data["items"]
    count = len(items)
    gap = 0.14
    row = min(1.35, (box.h - gap * (count - 1)) / count)
    head_x = box.x + 0.85
    head_w = 3.75
    detail_x = head_x + head_w + 0.35
    detail_w = box.right - detail_x - 0.25
    heads = [[Para(item["heading"], 14.5, bold=True)] for item in items]
    details = [[Para(item["detail"], 12.5)] for item in items]
    head_amount = c.uniform([(paras, head_w - 0.1, row - 0.14, f"item {i + 1} heading") for i, paras in enumerate(heads)], 11)
    detail_amount = c.uniform([(paras, detail_w - 0.1, row - 0.14, f"item {i + 1} detail") for i, paras in enumerate(details)], 10)
    for index in range(count):
        y = box.y + index * (row + gap)
        c.rect(Box(box.x, y, box.w, row), TAN)
        c.rect(Box(box.x, y, 0.07, row), RED)
        c.text(Box(box.x + 0.2, y, 0.55, row), [Para(str(index + 1), 22, bold=True, color=RED)], anchor="m", amount=0)
        c.text(Box(head_x, y, head_w, row), heads[index], anchor="m", amount=head_amount, floor=11, edit=c.at("items", index, "heading"))
        c.line(detail_x - 0.18, y + 0.16, detail_x - 0.18, y + row - 0.16, STONE_DARK)
        c.text(Box(detail_x, y, detail_w, row), details[index], anchor="m", amount=detail_amount, floor=10, edit=c.at("items", index, "detail"))


def _kpis(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    items = data["items"]
    kept = [index for index, point in enumerate(data.get("commentary") or []) if str(point).strip()]
    commentary = [data["commentary"][index] for index in kept]
    count = len(items)
    gap = 0.3
    tile_w = (box.w - gap * (count - 1)) / count
    tile_h = min(2.55, box.h * 0.58) if commentary else min(3.1, box.h)
    top = box.y if commentary else box.y + max(0.0, (box.h - tile_h) / 2 - 0.15)
    values = [[Para(item["value"], 46, bold=True, color=RED)] for item in items]
    value_amount = c.uniform([(paras, tile_w - 0.5, 0.9, f"item {i + 1} value") for i, paras in enumerate(values)], 26)
    texts = []
    edits = []
    for index, item in enumerate(items):
        paras = [Para(item["label"], 15, bold=True)]
        paths = [("items", index, "label")]
        if item.get("detail"):
            paras.append(Para(item["detail"], 12.5, color=GREY, space_before=4))
            paths.append(("items", index, "detail"))
        texts.append(paras)
        edits.append(c.fields(*paths))
    text_h = tile_h - 1.35
    text_amount = c.uniform([(paras, tile_w - 0.5, text_h, f"item {i + 1} label and detail") for i, paras in enumerate(texts)], 10)
    for index in range(count):
        x = box.x + index * (tile_w + gap)
        c.rect(Box(x, top, tile_w, tile_h), TAN)
        c.rect(Box(x, top, tile_w, 0.07), RED)
        c.text(Box(x + 0.22, top + 0.25, tile_w - 0.44, 0.95), values[index], anchor="m", amount=value_amount, floor=26, edit=c.at("items", index, "value"))
        c.text(Box(x + 0.22, top + 1.22, tile_w - 0.44, text_h), texts[index], amount=text_amount, floor=10, edit=edits[index])
    if commentary:
        y = top + tile_h + 0.3
        area = Box(box.x, y, box.w, box.bottom - y)
        columns = 2 if len(commentary) == 4 else 1
        per_column = (len(commentary) + columns - 1) // columns
        column_w = (area.w - 0.4 * (columns - 1)) / columns
        groups = []
        for column in range(columns):
            chunk = commentary[column * per_column : (column + 1) * per_column]
            groups.append([Para(point, 13, bullet=True, space_before=6) for point in chunk])
        amount = c.uniform([(paras, column_w - 0.1, area.h - 0.06, "commentary") for paras in groups], 10)
        for column, paras in enumerate(groups):
            indices = kept[column * per_column : (column + 1) * per_column]
            c.text(
                Box(area.x + column * (column_w + 0.4), area.y, column_w, area.h), paras, amount=amount, floor=10,
                edit=c.items(("commentary",), indices),
            )


def _cards(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    y = box.y
    intro = str(data.get("intro") or "").strip()
    if intro:
        paras = [Para(intro, 14, bold=True)]
        height = min(0.75, block_height(paras, box.w - 0.1) + 0.1)
        c.text(Box(box.x, y, box.w, height), paras, "intro", floor=11, anchor="m", edit=c.at("intro"))
        y += height + 0.18
    items = data["items"]
    count = len(items)
    gap = 0.22
    card_w = (box.w - gap * (count - 1)) / count
    card_h = box.bottom - y
    inner = card_w - 0.44
    heads = [[Para(item["heading"], 15, bold=True)] for item in items]
    head_amount = c.uniform([(paras, inner, 0.95, f"card {i + 1} heading") for i, paras in enumerate(heads)], 11.5)
    head_h = max(block_height(shrink(paras, head_amount, 11.5), inner) for paras in heads)
    points_top = 0.62 + head_h + 0.2
    bodies = [[Para(point, 13, bullet=True, space_before=7) for point in item["points"]] for item in items]
    body_amount = c.uniform(
        [(paras, inner - 0.1, card_h - points_top - 0.2, f"card {i + 1} points") for i, paras in enumerate(bodies)], 10
    )
    needed = max(block_height(shrink(paras, body_amount, 10), inner - 0.1) for paras in bodies)
    card_h = min(card_h, max(points_top + needed + 0.45, 2.8))
    for index in range(count):
        x = box.x + index * (card_w + gap)
        c.rect(Box(x, y, card_w, card_h), TAN)
        c.rect(Box(x, y, card_w, 0.07), RED)
        c.text(Box(x + 0.22, y + 0.2, inner, 0.32), [Para(f"{index + 1:02d}", 12, bold=True, color=RED)], amount=0)
        c.text(Box(x + 0.22, y + 0.55, inner, head_h + 0.1), heads[index], amount=head_amount, floor=11.5, edit=c.at("items", index, "heading"))
        c.line(x + 0.22, y + points_top - 0.08, x + card_w - 0.22, y + points_top - 0.08, STONE_DARK)
        c.text(
            Box(x + 0.22, y + points_top, inner, card_h - points_top - 0.15), bodies[index], amount=body_amount, floor=10,
            edit=c.items(("items", index, "points"), range(len(bodies[index]))),
        )


def _process(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    steps = data["steps"]
    count = len(steps)
    arrow_h = 0.8
    depth = 0.26
    pitch = box.w / count
    heads = [[Para(step["heading"], 13.5, bold=True, color=WHITE, align="c")] for step in steps]
    head_width = pitch - 2 * depth - 0.12
    head_amount = c.uniform([(paras, head_width, arrow_h - 0.12, f"step {i + 1} heading") for i, paras in enumerate(heads)], 10)
    panel_y = box.y + arrow_h + 0.18
    panel_h = box.bottom - panel_y
    bodies = [[Para(point, 13, bullet=True, space_before=7) for point in step["points"]] for step in steps]
    body_w = pitch - 0.12 - 0.4
    body_amount = c.uniform([(paras, body_w, panel_h - 0.36, f"step {i + 1} points") for i, paras in enumerate(bodies)], 10)
    needed = max(block_height(shrink(paras, body_amount, 10), body_w) for paras in bodies)
    panel_h = min(panel_h, max(needed + 0.5, 2.2))
    for index in range(count):
        x = box.x + index * pitch
        last = index == count - 1
        width = pitch if last else pitch + depth - 0.06
        shape_type = MSO_SHAPE.PENTAGON if index == 0 else MSO_SHAPE.CHEVRON
        arrow = c.rect(Box(x, box.y, width, arrow_h), RED if index % 2 == 0 else DARK_RED, shape=shape_type)
        arrow.adjustments[0] = depth / arrow_h
        left = 0.08 if index == 0 else depth + 0.04
        c.text_in(arrow, heads[index], head_amount, 10, (left, depth + 0.04, 0.04, 0.04), edit=c.at("steps", index, "heading"))
        panel = Box(x, panel_y, pitch - 0.12, panel_h)
        c.rect(panel, TAN)
        c.text(
            Box(panel.x + 0.2, panel.y + 0.16, panel.w - 0.4, panel.h - 0.3), bodies[index], amount=body_amount, floor=10,
            edit=c.items(("steps", index, "points"), range(len(bodies[index]))),
        )


def _roadmap(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    periods = data["periods"]
    lanes = data["lanes"]
    name_w = 2.3
    grid_x = box.x + name_w + 0.12
    column = (box.right - grid_x) / len(periods)
    header_h = 0.42
    for index, period in enumerate(periods):
        cell = Box(grid_x + index * column + 0.03, box.y, column - 0.06, header_h)
        c.rect(cell, STONE)
        c.text(cell, [Para(period, 12, bold=True, align="c")], f"period {index + 1}", floor=9, anchor="m", edit=c.at("periods", index))
    rows_y = box.y + header_h + 0.12
    gap = 0.12
    row = min(1.2, (box.bottom - rows_y - gap * (len(lanes) - 1)) / len(lanes))
    rows_bottom = rows_y + len(lanes) * row + gap * (len(lanes) - 1)
    spans = [_spans(lane["cells"]) for lane in lanes]
    names = [[Para(lane["name"], 13, bold=True)] for lane in lanes]
    name_amount = c.uniform([(paras, name_w - 0.35, row - 0.1, f"lane {i + 1} name") for i, paras in enumerate(names)], 10)
    groups = []
    for lane_index, lane_spans in enumerate(spans):
        for start, end, text in lane_spans:
            width = (end - start + 1) * column - 0.1 - 0.2
            groups.append(([Para(text, 11.5, align="c")], width, row - 0.2 - 0.08, f"lane {lane_index + 1} cell {start + 1}"))
    bar_amount = c.uniform(groups, 9)
    for index, lane in enumerate(lanes):
        y = rows_y + index * (row + gap)
        c.rect(Box(box.x, y, box.w, row), TAN)
        c.rect(Box(box.x, y, 0.07, row), RED)
        c.text(Box(box.x + 0.22, y, name_w - 0.3, row), names[index], anchor="m", amount=name_amount, floor=10, edit=c.at("lanes", index, "name"))
    for boundary in range(1, len(periods)):
        x = grid_x + boundary * column
        c.line(x, rows_y - 0.06, x, rows_bottom + 0.04, STONE_DARK, 0.5, dash=True)
    for index, lane_spans in enumerate(spans):
        y = rows_y + index * (row + gap)
        for start, end, text in lane_spans:
            bar = Box(grid_x + start * column + 0.05, y + 0.1, (end - start + 1) * column - 0.1, row - 0.2)
            c.rect(bar, WHITE, line=STONE_DARK)
            c.rect(Box(bar.x, bar.y, 0.05, bar.h), RED)
            edit = c.at("lanes", index, "cells", start)
            edit.also = [[c.base + ("lanes", index, "cells", cell) for cell in range(start + 1, end + 1)]]
            c.text(Box(bar.x + 0.1, bar.y, bar.w - 0.2, bar.h), [Para(text, 11.5, align="c")], anchor="m", amount=bar_amount, floor=9, edit=edit)


def _spans(cells: Sequence[str]) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    for index, raw in enumerate(cells):
        text = str(raw or "").strip()
        if not text:
            continue
        if spans and spans[-1][1] == index - 1 and spans[-1][2] == text:
            spans[-1] = (spans[-1][0], index, text)
        else:
            spans.append((index, index, text))
    return spans


JOURNEY_PANEL = 1.69
JOURNEY_GAP = 0.27
ARROW_GREY = "A6A6A6"
VIA_GREY = "7F7F7F"
SEPARATOR = "E5E1D7"


def _journey(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    lanes = data["lanes"]
    count = max(len(lane["steps"]) for lane in lanes)
    area_x = box.x + JOURNEY_PANEL + 0.33
    area_w = box.right - area_x
    column = min(1.9, area_w / count - 0.15)
    pitch = (area_w - column) / (count - 1)
    via_w = min(1.45, pitch - 0.45)
    lane_h = min(2.3, (box.h - JOURNEY_GAP * (len(lanes) - 1)) / len(lanes))
    first = box.y + (box.h - lane_h * len(lanes) - JOURNEY_GAP * (len(lanes) - 1)) / 2
    tops = [first + index * (lane_h + JOURNEY_GAP) for index in range(len(lanes))]

    def key_step(lane: dict) -> int:
        value = str(lane.get("highlight") or "").strip()
        return int(value) - 1 if value.isdigit() else -1

    def panel_paras(lane: dict) -> List[Para]:
        paras = [Para(lane["name"], 10, bold=True, caps=True)]
        if lane.get("description"):
            paras.append(Para(lane["description"], 10, space_before=8))
        return paras

    def step_paras(lane: dict, index: int) -> Tuple[List[Para], List[Para]]:
        step, color = lane["steps"][index], RED if index == key_step(lane) else BLACK
        return [Para(step["title"], 10, bold=True, color=color, align="c", caps=True)], [Para(step["text"], 9.5, color=color, align="c")]

    steps = [(i, j) for i, lane in enumerate(lanes) for j in range(len(lane["steps"]))]
    panel_amount = c.uniform([(panel_paras(lane), JOURNEY_PANEL - 0.24, lane_h - 0.3, f"lane {i + 1} name and description") for i, lane in enumerate(lanes)], 8)
    title_amount = c.uniform([(step_paras(lanes[i], j)[0], column, 0.36, f"lane {i + 1} step {j + 1} title") for i, j in steps], 8)
    title_h = max(block_height(shrink(step_paras(lanes[i], j)[0], title_amount, 8), column) for i, j in steps) + 0.02
    text_top = 1.01 + title_h
    text_h = lane_h - text_top
    text_amount = c.uniform([(step_paras(lanes[i], j)[1], column, text_h, f"lane {i + 1} step {j + 1} text") for i, j in steps], 8)
    vias = [(i, j) for i, j in steps if j and lanes[i]["steps"][j].get("via")]
    via_amount = c.uniform([([Para(lanes[i]["steps"][j]["via"], 8)], via_w, 0.38, f"lane {i + 1} step {j + 1} via") for i, j in vias], 7)

    for i, (lane, top) in enumerate(zip(lanes, tops)):
        panel = Box(box.x, top, JOURNEY_PANEL, lane_h)
        c.rect(panel, TAN)
        paths = [("lanes", i, "name")] + ([("lanes", i, "description")] if lane.get("description") else [])
        c.text(
            Box(panel.x + 0.12, top + 0.15, panel.w - 0.24, lane_h - 0.3), panel_paras(lane), anchor="m", amount=panel_amount,
            floor=8, edit=c.fields(*paths),
        )
        key = key_step(lane)
        centre_y = top + 0.29 + 0.325
        for j, step in enumerate(lane["steps"]):
            x = area_x + j * pitch
            middle = x + column / 2
            circle = Box(middle - 0.325, top + 0.29, 0.65, 0.65)
            c.rect(circle, RED if j == key else TAN, shape=MSO_SHAPE.OVAL)
            c.text(circle, [Para(str(j + 1), 16, bold=True, color=WHITE if j == key else GREY, align="c")], anchor="m", amount=0, inset=(0, 0))
            title, text = step_paras(lane, j)
            c.text(Box(x, top + 0.99, column, title_h), title, anchor="b", amount=title_amount, floor=8, inset=(0, 0), edit=c.at("lanes", i, "steps", j, "title"))
            c.text(Box(x, top + text_top, column, text_h), text, amount=text_amount, floor=8, inset=(0, 0.02), edit=c.at("lanes", i, "steps", j, "text"))
            if not j:
                continue
            start, end = middle - pitch + 0.325 + 0.08, middle - 0.325 - 0.08
            color = RED if j - 1 == key else ARROW_GREY
            _arc(c, start, end, centre_y - 0.12, color)
            if step.get("via"):
                size = max(7.0, 8 - via_amount)
                lines, width = len(wrap(step["via"], via_w, size)), via_w
                while width > 0.6 and len(wrap(step["via"], width - 0.05, size)) == lines:
                    width -= 0.05
                c.text(
                    Box((start + end) / 2 - width / 2, top - 0.14, width, 0.38),
                    [Para(step["via"], 8, color=RED if j - 1 == key else VIA_GREY, align="c", italic=True)],
                    anchor="b", amount=via_amount, floor=7, inset=(0, 0), edit=c.at("lanes", i, "steps", j, "via"),
                )
        if i < len(lanes) - 1:
            y = top + lane_h + JOURNEY_GAP / 2
            c.line(box.x, y, box.right, y, SEPARATOR, 1.5, dash="sysDot")


def _arc(c: Canvas, start: float, end: float, y: float, color: str) -> None:
    """A dotted arrow bowing upward from one step to the next."""
    rise, segments = 0.2, 16
    points = []
    for index in range(segments + 1):
        share = index / segments
        points.append((Inches(start + (end - start) * share), Inches(y - rise * 4 * share * (1 - share))))
    builder = c.slide.shapes.build_freeform(*points[0])
    builder.add_line_segments(points[1:], close=False)
    arrow = builder.convert_to_shape()
    arrow.shadow.inherit = False
    arrow.fill.background()
    arrow.line.color.rgb = RGBColor.from_string(color)
    arrow.line.width = Pt(1)
    line_props = arrow.line._get_or_add_ln()  # noqa: SLF001
    etree.SubElement(line_props, qn("a:prstDash")).set("val", "sysDot")
    etree.SubElement(line_props, qn("a:tailEnd")).set("type", "triangle")


TIMELINE_LABEL_W = 1.62
LEGEND = (
    ("submission", "Submissions"),
    ("review", "Review windows"),
    ("milestone", "Milestones"),
    ("meeting", "Meetings"),
    ("deliverable", "Key deliverables"),
)


def _timeline(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    start, end = parse_day(data["start"]), parse_day(data["end"])
    first = start - timedelta(days=start.weekday())
    weeks = [first + timedelta(days=7 * index) for index in range((end - first).days // 7 + 1)]
    chart = Box(box.x + TIMELINE_LABEL_W + 0.07, box.y, box.w - TIMELINE_LABEL_W - 0.07, box.h)

    def at(day: date) -> float:
        return chart.x + ((day - first).days + 0.5) / (7 * len(weeks)) * chart.w

    header_h = _calendar(c, chart, weeks)
    milestones = data["milestones"]
    deliverables = data.get("deliverables") or []
    meetings = data["meetings"]
    meeting_name = str(data.get("meeting_name") or "").strip()
    top_row = [(index, item) for index, item in enumerate(milestones) if item.get("kind") != "review"]
    review_row = [(index, item) for index, item in enumerate(milestones) if item.get("kind") == "review"]
    band = Box(chart.x, chart.y + header_h, chart.w, 1.6 if review_row else 0.85)
    c.rect(band, BAND_GREY)
    lower = Box(chart.x, band.bottom, chart.w, 0.75 if deliverables else 0)
    cards_top = lower.bottom + 0.14
    legend_y = box.bottom - 0.24
    cards = Box(chart.x, cards_top, chart.w, legend_y - 0.08 - cards_top)
    headings = (
        ("milestones_heading", "Key milestones", band, True),
        ("deliverables_heading", "Key deliverables", lower, True),
        ("meetings_heading", "Governance meetings", cards, False),
    )
    for key, default, area, bold in headings:
        if area.h > 0:
            paras = [Para(str(data.get(key) or default), 12, bold=bold, color=RED)]
            c.text(Box(box.x, area.y, TIMELINE_LABEL_W, area.h), paras, key.replace("_", " "), floor=9, anchor="m", edit=c.at(key))

    order = sorted(range(len(meetings)), key=lambda index: parse_day(meetings[index]["date"]))
    gap = 0.17
    card_w = (cards.w - gap * (len(order) - 1)) / len(order)
    marker_y = band.y + 0.08
    for position, index in enumerate(order):
        x = at(parse_day(meetings[index]["date"]))
        middle = cards.x + position * (card_w + gap) + card_w / 2
        jog = cards.y - 0.06 - 0.04 * (position % 2)
        c.line(x, marker_y + 0.06, x, jog, RED, 1)
        if abs(x - middle) > 0.01:
            c.line(x, jog, middle, jog, RED, 1)
        c.line(middle, jog, middle, cards.y, RED, 1)

    _events(c, "milestones", top_row, at, chart, marker_y, band.y + 0.83)
    _events(c, "milestones", review_row, at, chart, band.y + 0.9, band.bottom - 0.02)
    for meeting in meetings:
        x = at(parse_day(meeting["date"]))
        _marker(c, "meeting", x, x, marker_y)
    if deliverables:
        _events(c, "deliverables", list(enumerate(deliverables)), at, chart, lower.y + 0.1, lower.bottom - 0.02)

    inner = card_w - 0.24
    titles = [[Para(meeting["title"], 11, bold=True, align="c")] for meeting in meetings]
    title_amount = c.uniform([(titles[index], inner, 0.55, f"meeting {index + 1} title") for index in order], 9)
    title_h = max(block_height(shrink(paras, title_amount, 9), inner) for paras in titles) + 0.04
    body_top = 0.32 + title_h + 0.06
    bodies = [[Para(point, 10, bullet=True, space_before=4) for point in meeting["points"]] for meeting in meetings]
    body_amount = c.uniform([(bodies[index], inner, cards.h - body_top - 0.1, f"meeting {index + 1} points") for index in order], 8)
    for position, index in enumerate(order):
        x = cards.x + position * (card_w + gap)
        c.rect(Box(x, cards.y, card_w, cards.h), TAN, line=RED, line_width=1)
        when = parse_day(meetings[index]["date"])
        lead = f"{meeting_name} #{position + 1}: " if meeting_name else ""
        header = f"{lead}{when.strftime('%B')} {when.day}"
        if text_width(header, 9.5, bold=True) > inner - 0.1:
            header = f"{lead}{when.strftime('%b')} {when.day}"
        c.text(Box(x + 0.12, cards.y + 0.08, inner, 0.22), [Para(header, 10.5, bold=True, color=RED, align="c", italic=True)], floor=8, max_lines=1)
        c.text(Box(x + 0.12, cards.y + 0.32, inner, title_h), titles[index], amount=title_amount, floor=9, edit=c.at("meetings", index, "title"))
        c.text(
            Box(x + 0.12, cards.y + body_top, inner, cards.h - body_top - 0.06), bodies[index], amount=body_amount, floor=8,
            edit=c.items(("meetings", index, "points"), range(len(bodies[index]))),
        )

    used = {item.get("kind") or "milestone" for item in milestones} | {"meeting"} | ({"deliverable"} if deliverables else set())
    names = {"meeting": f"{meeting_name} meetings" if meeting_name else "Meetings", "deliverable": str(data.get("deliverables_heading") or "Key deliverables")}
    x = chart.x
    for kind, default in LEGEND:
        if kind not in used:
            continue
        name = names.get(kind, default)
        if kind in ("submission", "review"):
            mark_w = 0.5
            _marker(c, kind, x + 0.08, x + mark_w - 0.08, legend_y + 0.06)
        else:
            mark_w = 0.12
            _marker(c, kind, x + 0.06, x + 0.06, legend_y + 0.06)
        width = text_width(name, 9) + 0.15
        c.text(Box(x + mark_w + 0.04, legend_y, width, 0.24), [Para(name, 9, color=GREY)], anchor="m", amount=0, inset=(0.02, 0))
        x += mark_w + 0.04 + width + 0.25


def _calendar(c: Canvas, chart: Box, weeks: Sequence[date]) -> float:
    row = 0.23
    column = chart.w / len(weeks)
    months: List[List[int]] = []
    for index, week in enumerate(weeks):
        month = (week + timedelta(days=3)).replace(day=1)
        if months and months[-1][0] == month.toordinal():
            months[-1][2] += 1
        else:
            months.append([month.toordinal(), index, 1])
    for ordinal, first, count in months:
        cell = Box(chart.x + first * column, chart.y, count * column, row)
        c.rect(cell, BAND_GREY, line=BLACK, line_width=0.5)
        if cell.w >= 0.4:
            name = date.fromordinal(ordinal).strftime("%b")
            c.text(cell, [Para(name, 10.5, bold=True, align="c")], anchor="m", amount=0, inset=(0.02, 0))
    size = 10 if column >= 0.5 else 8
    for index, week in enumerate(weeks):
        cell = Box(chart.x + index * column, chart.y + row, column, row)
        c.rect(cell, BAND_GREY, line=BLACK, line_width=0.5)
        c.text(cell, [Para(f"{week.day:02d}.", size, bold=True, align="c")], anchor="m", amount=0, inset=(0.01, 0))
    return 2 * row


def _events(c: Canvas, group: str, items, at: Callable[[date], float], chart: Box, marker_y: float, bottom: float) -> None:
    """Markers on their dates, each labelled with its date and text in the space up to its neighbours."""
    placed = []
    for index, item in items:
        when, until = parse_day(item["date"]), parse_day(item["end"]) if item.get("end") else None
        start_x = at(when)
        end_x = at(until) if until else start_x
        placed.append(((start_x + end_x) / 2, start_x, end_x, index, item, when, until))
    placed.sort(key=lambda entry: entry[0])
    kind_default = "deliverable" if group == "deliverables" else "milestone"
    label_y = marker_y + 0.14
    for position, (anchor, start_x, end_x, index, item, when, until) in enumerate(placed):
        left = (anchor + placed[position - 1][0]) / 2 if position else chart.x
        right = (anchor + placed[position + 1][0]) / 2 if position < len(placed) - 1 else chart.right
        width = max(0.3, min(1.3, right - left - 0.04))
        x = max(left + 0.02, min(anchor - width / 2, right - width - 0.02))
        _marker(c, item.get("kind") or kind_default, start_x, end_x, marker_y)
        stamp = f"{when.month}/{when.day}" + (f"–{until.month}/{until.day}" if until and until != when else "")
        c.text(Box(x, label_y, width, 0.17), [Para(stamp, 9, align="c")], floor=7, inset=(0.01, 0))
        words = plain(str(item["label"])).split() or [""]
        if max(text_width(word, 8) for word in words) > width - 0.02:
            c.problems.append(
                f"Slide {c.number} ({c.kind}) {group} {index + 1} label: its date is too close to its neighbours for the label "
                "to fit. Shorten it to one or two short words, merge nearby items, or drop one."
            )
        c.text(
            Box(x, label_y + 0.17, width, bottom - label_y - 0.17), [Para(item["label"], 9, align="c")], f"{group} {index + 1} label",
            floor=8, inset=(0.01, 0), edit=c.at(group, index, "label"),
        )


def _marker(c: Canvas, kind: str, start_x: float, end_x: float, y: float) -> None:
    if kind in ("submission", "review"):
        width = max(end_x - start_x + 0.16, 0.36)
        pill = c.rect(
            Box((start_x + end_x) / 2 - width / 2, y - 0.02, width, 0.16), SUBMISSION_TAN if kind == "submission" else REVIEW_GREY,
            shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        )
        pill.adjustments[0] = 0.5
        if kind == "submission":
            for x in sorted({start_x, end_x}):
                c.rect(Box(x - 0.06, y, 0.12, 0.12), SUBMISSION_BROWN, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
    elif kind == "deliverable":
        c.rect(Box(start_x - 0.06, y + 0.02, 0.12, 0.08), DATE_BLUE, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
    elif kind == "meeting":
        c.rect(Box(start_x - 0.06, y, 0.12, 0.12), RED, shape=MSO_SHAPE.OVAL)
    else:
        c.rect(Box(start_x - 0.06, y, 0.12, 0.12), MILESTONE_GREEN, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)


def _table(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    columns = [str(value) for value in data["columns"]]
    rows = [[str(value or "") for value in row] for row in data["rows"]]
    count = len(columns)
    weights = []
    for index in range(count):
        longest = max([len(plain(columns[index]))] + [len(plain(row[index])) for row in rows if index < len(row)])
        weights.append(max(8, min(longest, 70)) ** 0.75 * (1.15 if index == 0 else 1.0))
    widths = [box.w * weight / sum(weights) for weight in weights]
    margin_x, margin_y = 0.08, 0.05

    def heights(size: float) -> Tuple[float, List[float]]:
        header = max(block_height([Para(text, size - 0.5, bold=True)], width - 2 * margin_x) for text, width in zip(columns, widths))
        body = []
        for row in rows:
            body.append(
                max(
                    block_height([Para(text, size, bold=index == 0)], widths[index] - 2 * margin_x)
                    for index, text in enumerate(row)
                )
                + 2 * margin_y
            )
        return header + 2 * margin_y, body

    size = 14.0
    header_h, body_h = heights(size)
    while header_h + sum(body_h) > box.h and size > 9:
        size -= 0.5
        header_h, body_h = heights(size)
    total = header_h + sum(body_h)
    if total > box.h:
        c.problems.append(
            f"Slide {c.number} (table): the table needs {total / box.h:.0%} of the space. Use fewer rows or shorter cells."
        )
    spare = max(0.0, box.h - total)
    pad = min(0.4, spare / max(1, len(rows)))
    body_h = [height + pad for height in body_h]
    frame = c.slide.shapes.add_table(
        len(rows) + 1, count, Inches(box.x), Inches(box.y), Inches(box.w), Inches(header_h + sum(body_h))
    )
    table = frame.table
    properties = table._tbl.tblPr  # noqa: SLF001
    properties.set("bandRow", "0")
    style = properties.find(qn("a:tableStyleId"))
    if style is None:
        style = etree.SubElement(properties, qn("a:tableStyleId"))
    style.text = NO_STYLE_TABLE
    for index, width in enumerate(widths):
        table.columns[index].width = Inches(width)
    table.rows[0].height = Inches(header_h)
    for index, height in enumerate(body_h, start=1):
        table.rows[index].height = Inches(height)
    lefts = [box.x + sum(widths[:index]) for index in range(count)]
    inset = (margin_x, margin_x, margin_y, margin_y)
    for column_index, text in enumerate(columns):
        paras = [Para(text, size - 0.5, bold=True, color=RED)]
        _cell(table.cell(0, column_index), paras, RED, 1.5, margin_x, margin_y, "b")
        c.record(Box(lefts[column_index], box.y, widths[column_index], header_h), paras, c.at("columns", column_index), inset, "b")
    y = box.y + header_h
    for row_index, row in enumerate(rows, start=1):
        for column_index, text in enumerate(row):
            paras = [Para(text, size, bold=column_index == 0)]
            _cell(table.cell(row_index, column_index), paras, STONE_DARK, 0.75, margin_x, margin_y, "m")
            cell = Box(lefts[column_index], y, widths[column_index], body_h[row_index - 1])
            c.record(cell, paras, c.at("rows", row_index - 1, column_index), inset, "m")
        y += body_h[row_index - 1]


def _cell(cell, paras: Sequence[Para], border: str, border_width: float, margin_x: float, margin_y: float, anchor: str) -> None:
    cell.margin_left = cell.margin_right = Inches(margin_x)
    cell.margin_top = cell.margin_bottom = Inches(margin_y)
    cell.vertical_anchor = ANCHORS[anchor]
    frame = cell.text_frame
    frame.word_wrap = True
    write_paragraphs(frame, paras)
    properties = cell._tc.get_or_add_tcPr()  # noqa: SLF001
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB", "a:noFill", "a:solidFill"):
        for node in properties.findall(qn(tag)):
            properties.remove(node)
    for position, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
        node = etree.Element(qn(tag))
        if tag == "a:lnB":
            node.set("w", str(int(Pt(border_width))))
            fill = etree.SubElement(node, qn("a:solidFill"))
            color = etree.SubElement(fill, qn("a:srgbClr"))
            color.set("val", border)
        else:
            node.set("w", "0")
            etree.SubElement(node, qn("a:noFill"))
        properties.insert(position, node)
    properties.insert(4, etree.Element(qn("a:noFill")))


def _number_format(unit: str, series: Sequence[dict]) -> str:
    decimals = 0
    for item in series:
        for value in item.get("values") or []:
            if isinstance(value, float) and not value.is_integer():
                decimals = max(decimals, min(2, len(repr(value).split(".")[1])))
    core = "#,##0" + ("." + "0" * decimals if decimals else "")
    unit = (unit or "").strip()
    prefix, suffix = "", ""
    if unit[:1] in "$€£" and unit:
        prefix, suffix = unit[0], unit[1:]
    elif unit:
        suffix = unit if unit in {"%", "x"} else f" {unit}"
    pieces = (f'"{prefix}"' if prefix else "") + core + (f'"{suffix}"' if suffix else "")
    return pieces


def _chart(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    chart_w = box.w * 0.63
    panel = Box(box.x + chart_w + 0.3, box.y, box.w - chart_w - 0.3, box.h)
    c.text(
        Box(box.x, box.y, chart_w, 0.32), [Para(data["chart_title"], 11, bold=True, spacing=100)], "chart_title", floor=9, anchor="m",
        edit=c.at("chart_title"),
    )
    kind = data.get("chart_type", "column")
    types = {
        "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "bar": XL_CHART_TYPE.BAR_CLUSTERED,
        "line": XL_CHART_TYPE.LINE_MARKERS,
        "stacked_column": XL_CHART_TYPE.COLUMN_STACKED,
    }
    chart_data = CategoryChartData()
    chart_data.categories = [str(category) for category in data["categories"]]
    series_list = data["series"]
    for series in series_list:
        chart_data.add_series(str(series["name"]), [float(value) for value in series["values"]])
    frame = c.slide.shapes.add_chart(
        types.get(kind, XL_CHART_TYPE.COLUMN_CLUSTERED),
        Inches(box.x), Inches(box.y + 0.4), Inches(chart_w), Inches(box.h - 0.4), chart_data,
    )
    chart = frame.chart
    chart.font.size = Pt(11)
    chart.font.color.rgb = RGBColor.from_string(BLACK)
    chart.has_title = False
    chart.has_legend = len(series_list) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(11)
    plot = chart.plots[0]
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.font.size = Pt(11)
    labels.number_format = _number_format(str(data.get("unit") or ""), series_list)
    labels.number_format_is_linked = False
    if kind == "stacked_column":
        labels.position = XL_LABEL_POSITION.CENTER
        plot.overlap = 100
    elif kind in {"column", "bar"}:
        labels.position = XL_LABEL_POSITION.OUTSIDE_END
    else:
        labels.position = XL_LABEL_POSITION.ABOVE
    if kind != "line":
        plot.gap_width = 70
    for index, series in enumerate(plot.series):
        color = RGBColor.from_string(SERIES_COLORS[index % len(SERIES_COLORS)])
        if kind == "line":
            series.format.line.color.rgb = color
            series.format.line.width = Pt(2.5)
            series.smooth = False
            series.marker.style = XL_MARKER_STYLE.CIRCLE
            series.marker.size = 7
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = color
            series.marker.format.line.color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = color
            series.invert_if_negative = False
        if kind == "stacked_column" and index == 0:
            series.data_labels.font.color.rgb = RGBColor.from_string(WHITE)
    value_axis = chart.value_axis
    value_axis.has_major_gridlines = False
    value_axis.visible = False
    category_axis = chart.category_axis
    category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW
    category_axis.format.line.color.rgb = RGBColor.from_string(STONE_DARK)
    category_axis.tick_labels.font.size = Pt(11)
    category_axis.has_major_gridlines = False
    if kind == "bar":
        category_axis.reverse_order = True

    c.rect(panel, TAN)
    c.text(Box(panel.x + 0.25, panel.y + 0.18, panel.w - 0.5, 0.3), [Para("Key takeaways", 10, bold=True, color=RED, caps=True, spacing=200)], amount=0)
    highlights = data["highlights"]
    area_y = panel.y + 0.65
    area_h = panel.h - 0.8
    text_w = panel.w - 0.25 - 0.55 - 0.2
    paras = [[Para(point, 12.5)] for point in highlights]
    gap = 0.22
    amount = 0.0
    while True:
        heights = [block_height(shrink(item, amount, 10), text_w - 0.1) + 0.06 for item in paras]
        if sum(heights) + gap * (len(paras) - 1) <= area_h or 12.5 - amount <= 10:
            break
        amount += 0.5
    total = sum(heights) + gap * (len(paras) - 1)
    if total > area_h:
        c.problem("highlights", [para for item in paras for para in item], total / area_h)
    y = area_y
    for index, (item, height) in enumerate(zip(paras, heights)):
        badge = c.rect(Box(panel.x + 0.25, y + 0.02, 0.3, 0.3), RED, shape=MSO_SHAPE.OVAL)
        c.text_in(badge, [Para(str(index + 1), 11, bold=True, color=WHITE, align="c")], 0, 11, (0, 0, 0, 0))
        c.text(Box(panel.x + 0.25 + 0.5, y, text_w, max(height, 0.34)), item, amount=amount, floor=10, edit=c.at("highlights", index))
        y += max(height, 0.34) + gap


def _comparison(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    gap = 0.5
    width = (box.w - gap) / 2
    header_h = 0.55
    sides = [(data["left"], STONE, BLACK), (data["right"], RED, WHITE)]
    bodies = [[Para(point, 13.5, bullet=True, space_before=9) for point in side["points"]] for side, _fill, _color in sides]
    body_h = box.h - header_h
    amount = c.uniform([(paras, width - 0.5, body_h - 0.4, f"{name} points") for paras, name in zip(bodies, ("left", "right"))], 10)
    needed = max(block_height(shrink(paras, amount, 10), width - 0.5) for paras in bodies)
    body_h = min(body_h, max(needed + 0.6, 2.4))
    for index, (side, fill, color) in enumerate(sides):
        key = "left" if index == 0 else "right"
        x = box.x + index * (width + gap)
        header = Box(x, box.y, width, header_h)
        c.rect(header, fill)
        c.text(header, [Para(side["title"], 15, bold=True, color=color)], f"{key} title", floor=11, anchor="m", inset=(0.25, 0.03), edit=c.at(key, "title"))
        body = Box(x, box.y + header_h, width, body_h)
        c.rect(body, TAN)
        c.text(
            Box(body.x + 0.25, body.y + 0.2, body.w - 0.5, body.h - 0.4), bodies[index], amount=amount, floor=10,
            edit=c.items((key, "points"), range(len(bodies[index]))),
        )
    middle = box.y + (header_h + body_h) / 2
    arrow = c.rect(Box(box.x + width + 0.12, middle - 0.22, gap - 0.24, 0.44), RED, shape=MSO_SHAPE.CHEVRON)
    arrow.adjustments[0] = 0.5


def _rows(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    items = data["items"]
    count = len(items)
    left_w = 4.9
    right_x = box.x + left_w + 0.25
    right_w = box.right - right_x
    header_h = 0.3
    for x, key in ((box.x, "left_header"), (right_x, "right_header")):
        c.text(
            Box(x, box.y, 4.5, header_h), [Para(data[key], 10, color=GREY, caps=True, spacing=200)], "column header", floor=8, anchor="m",
            edit=c.at(key),
        )
    rows_y = box.y + header_h + 0.12
    gap = 0.14
    row = min(1.3, (box.bottom - rows_y - gap * (count - 1)) / count)
    depth = 0.28
    lefts = []
    edits = []
    for index, item in enumerate(items):
        paras = [Para(item["heading"], 14, bold=True, color=RED)]
        paths = [("items", index, "heading")]
        if item.get("detail"):
            paras.append(Para(item["detail"], 12, space_before=2))
            paths.append(("items", index, "detail"))
        lefts.append(paras)
        edits.append(c.fields(*paths))
    left_amount = c.uniform([(paras, left_w - 0.25 - depth - 0.2, row - 0.12, f"item {i + 1} heading and detail") for i, paras in enumerate(lefts)], 10)
    rights = [[Para(point, 12.5, bullet=len(item["points"]) > 1, space_before=6) for point in item["points"]] for item in items]
    right_amount = c.uniform([(paras, right_w - 0.5, row - 0.14, f"item {i + 1} points") for i, paras in enumerate(rights)], 10)
    for index in range(count):
        y = rows_y + index * (row + gap)
        arrow = c.rect(Box(box.x, y, left_w, row), TAN, shape=MSO_SHAPE.PENTAGON)
        arrow.adjustments[0] = depth / min(row, left_w)
        c.text(Box(box.x + 0.22, y, left_w - 0.22 - depth - 0.1, row), lefts[index], anchor="m", amount=left_amount, floor=10, edit=edits[index])
        c.rect(Box(right_x, y, right_w, row), WHITE, line=STONE)
        c.text(
            Box(right_x + 0.22, y, right_w - 0.4, row), rights[index], anchor="m", amount=right_amount, floor=10,
            edit=c.items(("items", index, "points"), range(len(rights[index]))),
        )


HOUSE_RAIL = 0.46
HOUSE_TOP = 0.47
HOUSE_BOTTOM = 0.50


def _strategy_house(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    _house_frame(c, box)
    bands = (("aspiration", box.y, HOUSE_TOP), ("outcome", box.bottom - HOUSE_BOTTOM, HOUSE_BOTTOM))
    for key, y, height in bands:
        band = Box(box.x + 0.17, y, box.w - 0.34, height)
        c.fills.append((band, DEEP_RED))
        paras = [Para(data[key], 16, bold=True, color=WHITE, align="c", caps=True)]
        c.text(band, paras, key, floor=11, anchor="m", inset=(0.1, 0.02), max_lines=1, edit=c.at(key))
    inside = Box(box.x + HOUSE_RAIL, box.y + HOUSE_TOP, box.w - 2 * HOUSE_RAIL, box.h - HOUSE_TOP - HOUSE_BOTTOM)
    area = Box(inside.x + 0.3, inside.y + 0.4, inside.w - 0.6, inside.h - 0.75)
    pillars = data["pillars"]
    count = len(pillars)
    gap = 0.225
    width = (area.w - gap * (count - 1)) / count
    text_w = width - 0.5
    icon = 0.42
    with_points = any(pillar.get("points") for pillar in pillars)
    icon_top = area.y + (0.3 if with_points else 0.7)
    head_top = icon_top + 0.61
    head_size, head_floor = (15, 11) if with_points else (18, 12)
    head_room = 0.95 if with_points else area.bottom - head_top - 0.2
    heads = [[Para(pillar["heading"], head_size, bold=True, align="c")] for pillar in pillars]
    head_amount = c.uniform([(paras, text_w, head_room, f"pillar {i + 1} heading") for i, paras in enumerate(heads)], head_floor)
    head_h = max(block_height(shrink(paras, head_amount, head_floor), text_w) for paras in heads) + 0.08
    points_top = head_top + head_h + 0.22
    points_w = width - 0.36
    bodies = [[Para(point, 12.5, bullet=True, space_before=6) for point in pillar.get("points") or []] for pillar in pillars]
    body_amount = c.uniform(
        [(paras, points_w, area.bottom - points_top - 0.15, f"pillar {i + 1} points") for i, paras in enumerate(bodies) if paras], 10
    )
    for index in range(count):
        x = area.x + index * (width + gap)
        c.rect(Box(x, area.y, width, area.h), LIGHT_GREY, line=STONE_DARK, line_width=1)
        badge = c.rect(Box(x + (width - icon) / 2, icon_top, icon, icon), None, line=DEEP_RED, shape=MSO_SHAPE.OVAL, line_width=1.25)
        c.text_in(badge, [Para(str(index + 1), 12, bold=True, color=DEEP_RED, align="c")], 0, 12, (0, 0, 0, 0))
        c.text(
            Box(x + 0.25, head_top, text_w, head_h), heads[index], amount=head_amount, floor=head_floor, edit=c.at("pillars", index, "heading")
        )
        if not bodies[index]:
            continue
        c.line(x + 0.3, points_top - 0.11, x + width - 0.3, points_top - 0.11, STONE_DARK)
        c.text(
            Box(x + 0.18, points_top, points_w, area.bottom - points_top - 0.1), bodies[index], amount=body_amount, floor=10,
            edit=c.items(("pillars", index, "points"), range(len(bodies[index]))),
        )


def _house_frame(c: Canvas, box: Box) -> None:
    """One closed loop around the pillars, notched so it reads clockwise: up the left rail, down the right."""
    width, height, rail = box.w, box.h, HOUSE_RAIL
    depth, gap = 0.24, 0.39
    left, right = 0.455 * height, 0.502 * height
    upper = [
        (width, 0), (width, right), (width - rail / 2, right + depth), (width - rail, right), (width - rail, HOUSE_TOP),
        (rail, HOUSE_TOP), (rail, left), (rail / 2, left - depth), (0, left),
    ]
    lower = [
        (rail, left + gap), (rail, height - HOUSE_BOTTOM), (width - rail, height - HOUSE_BOTTOM), (width - rail, right + gap),
        (width - rail / 2, right + gap + depth), (width, right + gap), (width, height), (0, height), (0, left + gap),
    ]

    def point(x: float, y: float) -> Tuple[int, int]:
        return Inches(box.x + x), Inches(box.y + y)

    builder = c.slide.shapes.build_freeform(*point(0, 0))
    builder.add_line_segments([point(x, y) for x, y in upper], close=True)
    builder.move_to(*point(rail / 2, left + gap - depth))
    builder.add_line_segments([point(x, y) for x, y in lower], close=True)
    frame = builder.convert_to_shape()
    frame.shadow.inherit = False
    frame.fill.solid()
    frame.fill.fore_color.rgb = RGBColor.from_string(DEEP_RED)
    frame.line.fill.background()


def _statement(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    kept = [index for index, point in enumerate(data.get("points") or []) if str(point).strip()]
    points = [data["points"][index] for index in kept]
    statement_h = box.h * (0.52 if points else 0.8)
    paras = [Para(data["statement"], 30, accent=RED)]
    result = fit(paras, box.w * 0.8 - 0.1, statement_h - 0.06, 20)
    if not result.ok:
        c.problem("statement", paras, result.ratio)
    used = block_height(shrink(paras, result.shrink, 20), box.w * 0.8 - 0.1) + 0.1
    top = box.y + (0.1 if points else max(0.0, (box.h - used) / 2 - 0.2))
    c.rect(Box(box.x, top, 0.09, used), RED)
    c.text(Box(box.x + 0.35, top, box.w * 0.8, used + 0.05), paras, amount=result.shrink, floor=20, edit=c.at("statement"))
    if not points:
        return
    y = max(top + used + 0.45, box.y + statement_h)
    count = len(points)
    gap = 0.35
    width = (box.w - gap * (count - 1)) / count
    bodies = [[Para(point, 13.5)] for point in points]
    amount = c.uniform([(paras, width - 0.1, box.bottom - y - 0.5, f"point {i + 1}") for i, paras in enumerate(bodies)], 10)
    for index in range(count):
        x = box.x + index * (width + gap)
        c.line(x, y, x + width, y, RED, 1.5)
        c.text(Box(x, y + 0.08, width, 0.36), [Para(f"{index + 1:02d}", 13, bold=True, color=RED)], amount=0)
        c.text(Box(x, y + 0.45, width, box.bottom - y - 0.45), bodies[index], amount=amount, floor=10, edit=c.at("points", kept[index]))


def _agenda(c: Canvas, data: dict, box: Box, deck: dict) -> None:
    sections = [(position, item) for position, item in enumerate(deck.get("sections") or []) if isinstance(item, dict)]
    if not sections:
        return
    row = min(1.1, box.h / len(sections))
    for index, (position, section) in enumerate(sections):
        y = box.y + index * row
        c.text(Box(box.x, y, 0.9, row), [Para(f"{index + 1:02d}", 26, bold=True, color=RED)], anchor="m", amount=0)
        c.text(
            Box(box.x + 1.0, y, 4.4, row), [Para(str(section.get("name") or ""), 18, bold=True)], f"section {index + 1} name", floor=13, anchor="m",
            edit=Edit([("sections", position, "name")]),
        )
        c.text(
            Box(box.x + 5.6, y, box.w - 5.6, row), [Para(str(section.get("summary") or ""), 13, color=GREY)], f"section {index + 1} summary",
            floor=10, anchor="m", edit=Edit([("sections", position, "summary")]),
        )
        c.line(box.x, y + row, box.right, y + row, STONE)


DRAW: Dict[str, Callable[[Canvas, dict, Box, dict], None]] = {
    "executive_summary": _executive_summary,
    "kpis": _kpis,
    "cards": _cards,
    "process": _process,
    "journey": _journey,
    "roadmap": _roadmap,
    "timeline": _timeline,
    "table": _table,
    "chart": _chart,
    "comparison": _comparison,
    "rows": _rows,
    "strategy_house": _strategy_house,
    "statement": _statement,
    "agenda": _agenda,
}
