"""Measure wrapped text so every box is sized before it is drawn."""

import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

FONT_FILES = {
    False: (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    True: (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
}
# The brand fonts are not installed where previews render, so widths are measured with a
# metric-compatible sans and padded.
WIDTH_SAFETY = 1.07
LINE_SPACING = 1.2
BULLET_INDENT = 0.17
BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*")


@dataclass(frozen=True)
class Para:
    text: str
    size: float
    bold: bool = False
    color: str = "000000"
    bullet: bool = False
    space_before: float = 0.0
    align: str = "l"
    caps: bool = False
    spacing: int = 0
    accent: str = ""


@lru_cache(maxsize=4)
def _font(bold: bool):
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    for path in FONT_FILES[bold]:
        try:
            return ImageFont.truetype(path, 100)
        except OSError:
            continue
    return None


def plain(text: str) -> str:
    return BOLD_SPAN.sub(r"\1", text or "")


def runs(text: str) -> List[Tuple[str, bool]]:
    pieces: List[Tuple[str, bool]] = []
    position = 0
    for match in BOLD_SPAN.finditer(text or ""):
        if match.start() > position:
            pieces.append((text[position : match.start()], False))
        pieces.append((match.group(1), True))
        position = match.end()
    if position < len(text or ""):
        pieces.append((text[position:], False))
    return [piece for piece in pieces if piece[0]]


def text_width(text: str, size: float, bold: bool = False, spacing: int = 0) -> float:
    font = _font(bold)
    if font is not None:
        points = font.getlength(text) * size / 100
    else:
        points = len(text) * size * (0.56 if bold else 0.5)
    points += len(text) * spacing / 100
    return points * WIDTH_SAFETY / 72


def wrap(text: str, width: float, size: float, bold: bool = False, spacing: int = 0) -> List[str]:
    lines: List[str] = []
    for raw in plain(text).split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}" if current else word
            if text_width(candidate, size, bold, spacing) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = word
            while text_width(current, size, bold, spacing) > width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and text_width(current[:cut], size, bold, spacing) > width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return lines


def line_height(size: float) -> float:
    return size * LINE_SPACING / 72


def para_height(para: Para, width: float) -> float:
    usable = width - (BULLET_INDENT if para.bullet else 0)
    text = para.text.upper() if para.caps else para.text
    count = len(wrap(text, usable, para.size, para.bold, para.spacing))
    return count * line_height(para.size) + para.space_before / 72


def block_height(paras: Sequence[Para], width: float) -> float:
    total = 0.0
    for index, para in enumerate(paras):
        height = para_height(para, width)
        if index == 0:
            height -= para.space_before / 72
        total += height
    return total


def line_count(para: Para, width: float) -> int:
    usable = width - (BULLET_INDENT if para.bullet else 0)
    text = para.text.upper() if para.caps else para.text
    return len(wrap(text, usable, para.size, para.bold, para.spacing))


def shrink(paras: Sequence[Para], amount: float, floor: float) -> List[Para]:
    return [
        replace(para, size=max(min(floor, para.size), para.size - amount), space_before=para.space_before * 0.8 if amount else para.space_before)
        for para in paras
    ]


@dataclass
class Fit:
    shrink: float
    ok: bool
    ratio: float


def fit(paras: Sequence[Para], width: float, height: float, floor: float, max_lines: Optional[int] = None) -> Fit:
    """Find the smallest uniform reduction in points that makes the paragraphs fit the box."""
    largest = max((para.size for para in paras), default=floor)
    amount = 0.0
    while True:
        trial = shrink(paras, amount, floor)
        needed = block_height(trial, width)
        lines_ok = max_lines is None or all(line_count(para, width) <= max_lines for para in trial)
        if needed <= height + 1e-6 and lines_ok:
            return Fit(amount, True, needed / height if height else 1.0)
        if all(para.size <= floor for para in trial) or largest - amount <= floor:
            return Fit(amount, False, needed / height if height else 99.0)
        amount += 0.5


def fit_all(groups: Sequence[Tuple[Sequence[Para], float, float]], floor: float) -> Fit:
    """One shrink amount for sibling boxes, so parallel items share a type size."""
    results = [fit(paras, width, height, floor) for paras, width, height in groups]
    if not results:
        return Fit(0.0, True, 0.0)
    return Fit(
        max(result.shrink for result in results),
        all(result.ok for result in results),
        max(result.ratio for result in results),
    )
