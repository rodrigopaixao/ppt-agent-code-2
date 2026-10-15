import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER

from app.models.presentation import LayoutName


@dataclass(frozen=True)
class LayoutChoice:
    master_index: int
    layout_index: int


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def inspect_template(path: Path) -> Dict:
    presentation = Presentation(str(path))
    layouts: List[Dict] = []
    for index, layout in enumerate(presentation.slide_layouts):
        placeholders = []
        for placeholder in layout.placeholders:
            placeholders.append(
                {
                    "name": placeholder.name,
                    "index": placeholder.placeholder_format.idx,
                    "type": str(placeholder.placeholder_format.type),
                }
            )
        layouts.append({"index": index, "name": layout.name, "placeholders": placeholders})
    return {
        "path": str(path),
        "width": presentation.slide_width,
        "height": presentation.slide_height,
        "slide_count": len(presentation.slides),
        "layouts": layouts,
        "mapping": {
            key.value: {"master": value.master_index, "layout": value.layout_index}
            for key, value in map_layouts(presentation).items()
        },
    }


def iter_layouts(presentation: Presentation) -> Iterator[Tuple[int, int, object]]:
    for master_index, master in enumerate(presentation.slide_masters):
        for layout_index, layout in enumerate(master.slide_layouts):
            yield master_index, layout_index, layout


def _placeholder_types(layout) -> List:
    return [placeholder.placeholder_format.type for placeholder in layout.placeholders]


def _large_body_count(layout) -> int:
    count = 0
    for placeholder in layout.placeholders:
        if placeholder.placeholder_format.type not in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT):
            continue
        if placeholder.height is not None and placeholder.height.inches >= 1:
            count += 1
    return count


def _score(name: str, layout, semantic: LayoutName) -> int:
    types = _placeholder_types(layout)
    large_bodies = _large_body_count(layout)
    score = 0
    if semantic == LayoutName.TITLE:
        if "title slide" in name:
            score += 200
        elif "cover" in name or name == "title":
            score += 120
        if PP_PLACEHOLDER.CENTER_TITLE in types:
            score += 40
        if "chapter" in name or "agenda" in name:
            score -= 100
        score -= len(list(layout.placeholders))
    elif semantic == LayoutName.SECTION:
        if "chapter" in name:
            score += 200
        elif "section" in name or "divider" in name:
            score += 160
        if PP_PLACEHOLDER.TITLE in types:
            score += 20
        if "numbered" in name:
            score -= 80
    elif semantic == LayoutName.TITLE_CONTENT:
        if "title and content" in name:
            score += 220
        elif "top header" in name and "numbered" not in name:
            score += 180
            if name.startswith("top header"):
                score += 20
        elif "content" in name:
            score += 100
        if PP_PLACEHOLDER.TITLE in types and large_bodies >= 1:
            score += 30
        if any(term in name for term in ("agenda", "org chart", "headshot", "numbered")):
            score -= 80
    elif semantic == LayoutName.TWO_COLUMN:
        if any(term in name for term in ("one vs", "two column", "comparison", "side by side")):
            score += 200
        if name in {"one vs two", "two column comparison"}:
            score += 30
        if large_bodies >= 2:
            score += 40
        if "numbered" in name:
            score -= 40
    elif semantic == LayoutName.BLANK:
        if "blank" in name:
            score += 200
        if not types:
            score += 40
    return score


def map_layouts(presentation: Presentation) -> Dict[LayoutName, LayoutChoice]:
    candidates = list(iter_layouts(presentation))
    mapping: Dict[LayoutName, LayoutChoice] = {}
    for semantic in LayoutName:
        best_score = 0
        best = LayoutChoice(0, 0)
        for master_index, layout_index, layout in candidates:
            score = _score(normalize(layout.name), layout, semantic)
            if score > best_score:
                best_score = score
                best = LayoutChoice(master_index, layout_index)
        mapping[semantic] = best
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a PowerPoint template.")
    parser.add_argument("--template", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_template(args.template), indent=2))


if __name__ == "__main__":
    main()
