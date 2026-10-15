"""The deck document the writer produces: slide types, their fields, and structural checks."""

import json
import re
from typing import Dict, List, Optional, Tuple


def S(limit: int, required: bool = True) -> dict:
    return {"kind": "str", "limit": limit, "required": required}


def L(item: dict, low: int, high: int, required: bool = True) -> dict:
    return {"kind": "list", "item": item, "low": low, "high": high, "required": required}


def O(fields: Dict[str, dict], required: bool = True) -> dict:
    return {"kind": "obj", "fields": fields, "required": required}


NUMBERS = {"kind": "numbers", "required": True}

HEADER = {
    "section": S(40),
    "label": S(28),
    "headline": S(125),
    "subheader": S(70, False),
    "source": S(260, False),
    "takeaway": S(150, False),
}

CHART_TYPES = ("column", "bar", "line", "stacked_column")

TYPES: Dict[str, dict] = {
    "executive_summary": {
        "use": "The answer first. One row per key message, in the order of the sections that follow.",
        "fields": {"items": L(O({"heading": S(80), "detail": S(230)}), 3, 5)},
        "example": {"items": [{"heading": "Message as a short sentence", "detail": "The evidence behind it, with **the key figure** bolded."}]},
    },
    "kpis": {
        "use": "Two to four headline figures that carry the point. Optional commentary bullets explain what drives them.",
        "fields": {
            "items": L(O({"value": S(9), "label": S(45), "detail": S(120, False)}), 2, 4),
            "commentary": L(S(150), 0, 4, False),
        },
        "example": {"items": [{"value": "13.2%", "label": "CET1 ratio", "detail": "Up 40 bps year over year"}], "commentary": ["Driver of the result"]},
    },
    "cards": {
        "use": "Two to five parallel ideas of equal weight: pillars, options, priorities, capabilities.",
        "fields": {
            "intro": S(170, False),
            "items": L(O({"heading": S(45), "points": L(S(120), 1, 4)}), 2, 5),
        },
        "example": {"intro": "One sentence framing the set", "items": [{"heading": "Pillar name", "points": ["What it means", "How it shows up"]}]},
    },
    "process": {
        "use": "A sequence where order matters: stages of a journey, steps of a method, a funnel.",
        "fields": {"steps": L(O({"heading": S(32), "points": L(S(110), 1, 3)}), 3, 6)},
        "example": {"steps": [{"heading": "Discover", "points": ["What happens here", "**Gap**: where clients drop off"]}]},
    },
    "roadmap": {
        "use": "Work phased over time: workstreams (lanes) across periods. Identical text in neighbouring cells merges into one bar.",
        "fields": {
            "periods": L(S(16), 3, 6),
            "lanes": L(O({"name": S(28), "cells": L(S(48, False), 3, 6)}), 2, 5),
        },
        "example": {"periods": ["Q1", "Q2", "Q3"], "lanes": [{"name": "Data", "cells": ["Client 360 MVP", "Client 360 MVP", "Scale"]}]},
    },
    "table": {
        "use": "Many attributes across several items, when a grid is the clearest form (targets vs. actuals, option comparison, owners and dates).",
        "fields": {
            "columns": L(S(30), 2, 6),
            "rows": L(L(S(90, False), 2, 6), 2, 8),
        },
        "example": {"columns": ["Metric", "Actual", "Target"], "rows": [["ROE", "11.8%", "14%+"]]},
    },
    "chart": {
        "use": "A trend over time or a comparison of quantities, with two to four takeaways beside it.",
        "fields": {
            "chart_type": S(16),
            "chart_title": S(60),
            "unit": S(6, False),
            "categories": L(S(18), 2, 10),
            "series": L(O({"name": S(30), "values": NUMBERS}), 1, 3),
            "highlights": L(S(160), 2, 4),
        },
        "example": {
            "chart_type": "column",
            "chart_title": "Adjusted net income, $B",
            "unit": "$B",
            "categories": ["2023", "2024", "2025"],
            "series": [{"name": "Adjusted net income", "values": [8.4, 8.6, 9.5]}],
            "highlights": ["**+10.2%** in 2025 after two flat years"],
        },
    },
    "comparison": {
        "use": "Two sides set against each other: today vs. target, risks vs. mitigations, option A vs. option B.",
        "fields": {
            "left": O({"title": S(34), "points": L(S(130), 2, 5)}),
            "right": O({"title": S(34), "points": L(S(130), 2, 5)}),
        },
        "example": {"left": {"title": "Today", "points": ["..."]}, "right": {"title": "Target state", "points": ["..."]}},
    },
    "rows": {
        "use": "Three to five items, each with consequences: theme to implication, risk to mitigation, pillar to initiatives.",
        "fields": {
            "left_header": S(30),
            "right_header": S(30),
            "items": L(O({"heading": S(45), "detail": S(110, False), "points": L(S(140), 1, 2)}), 3, 5),
        },
        "example": {"left_header": "Risk", "right_header": "Mitigation", "items": [{"heading": "Cyber and fraud", "detail": "Rising attack volume", "points": ["**24/7 monitoring** and controls testing"]}]},
    },
    "statement": {
        "use": "One pivotal message that deserves a whole slide, with up to three short supporting points. Use at most once.",
        "fields": {"statement": S(170), "points": L(S(140), 0, 3, False)},
        "example": {"statement": "The message, with **the key phrase** emphasised", "points": ["Support"]},
    },
    "agenda": {
        "use": "Lists the sections. The renderer fills it from the sections list; supply only the header fields.",
        "fields": {},
        "example": {},
    },
    "section": {
        "use": "A divider that opens a section. Only worth it in decks of twelve or more slides.",
        "fields": {},
        "example": {},
    },
}

TOP_LEVEL = {
    "storyline": O({"audience": S(200), "objective": S(300), "governing_thought": S(300)}),
    "cover": O({"title": S(70), "subtitle": S(140, False), "date": S(40, False)}),
    "sections": L(O({"name": S(40), "summary": S(120)}), 1, 6),
}


def editor_schema() -> dict:
    return {
        "header": HEADER,
        "cover": TOP_LEVEL["cover"],
        "sections": TOP_LEVEL["sections"],
        "chart_types": list(CHART_TYPES),
        "types": {name: {"use": spec["use"], "fields": spec["fields"], "example": spec["example"]} for name, spec in TYPES.items()},
    }


def catalog() -> str:
    lines = []
    for name, spec in TYPES.items():
        lines.append(f"### {name}")
        lines.append(spec["use"])
        if spec["fields"]:
            lines.append("Fields: " + _describe_fields(spec["fields"]))
        example = {"type": name, "section": "Section name", "label": "Topic", "headline": "The point of the slide as a sentence"}
        example.update(spec["example"])
        lines.append("Example: " + json.dumps(example, ensure_ascii=False))
        lines.append("")
    return "\n".join(lines)


def header_rules() -> str:
    return _describe_fields(HEADER)


def _describe_fields(fields: Dict[str, dict]) -> str:
    return "; ".join(f"{name} {_describe(spec)}" for name, spec in fields.items())


def _describe(spec: dict) -> str:
    optional = "" if spec.get("required", True) else " optional"
    if spec["kind"] == "str":
        return f"(text <= {spec['limit']}{optional})"
    if spec["kind"] == "numbers":
        return "(list of numbers, one per category)"
    if spec["kind"] == "list":
        return f"({spec['low']}-{spec['high']} x {_describe(spec['item'])}{optional})"
    inner = ", ".join(f"{key} {_describe(value)}" for key, value in spec["fields"].items())
    return "{" + inner + "}" + optional


def structure_errors(deck: dict, editorial: bool = True) -> List[str]:
    """Errors that stop the deck from rendering. Editorial rules (text limits, deck conventions) apply to the writer only."""
    if not isinstance(deck, dict):
        return ["Return one JSON object with storyline, cover, sections, and slides."]
    errors: List[str] = []
    for key, spec in TOP_LEVEL.items():
        if key == "storyline" and not editorial:
            continue
        errors.extend(_check(deck.get(key), spec, key, editorial))
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return errors + ["slides must be a non-empty list."]
    if len(slides) > 28:
        errors.append(f"The deck has {len(slides)} slides; keep it to 28 or fewer.")
    names = _section_names(deck)
    first = slides[0].get("type") if isinstance(slides[0], dict) else None
    if editorial and len(slides) >= 5 and first != "executive_summary":
        errors.append("Slide 1 must be the executive_summary: open with the answer and the key messages of each section.")
    previous = None
    tables = 0
    for number, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            errors.append(f"Slide {number} must be an object.")
            continue
        kind = slide.get("type")
        if kind not in TYPES:
            errors.append(f"Slide {number} has unknown type {kind!r}. Use one of: {', '.join(TYPES)}.")
            continue
        where = f"Slide {number} ({kind})"
        if kind == "section":
            if slide.get("section") not in names:
                errors.append(f"{where} section must be one of the section names: {', '.join(names)}.")
            continue
        header = dict(HEADER)
        if kind == "agenda":
            header = {"label": S(28, False), "headline": S(125, False)}
        errors.extend(_check_fields(slide, header, where, editorial))
        if kind != "agenda" and slide.get("section") not in names:
            errors.append(f"{where} section must exactly match one of the section names: {', '.join(names)}.")
        label, headline = str(slide.get("label") or ""), str(slide.get("headline") or "")
        if editorial and label and headline and len(label) + len(headline) > 135:
            errors.append(f"{where} label plus headline is {len(label) + len(headline)} characters; keep it under 135.")
        errors.extend(_check_fields(slide, TYPES[kind]["fields"], where, editorial))
        allowed = set(header) | set(TYPES[kind]["fields"]) | {"type", "section"}
        extra = sorted(set(slide) - allowed)
        if extra:
            errors.append(f"{where} has fields this type does not use: {', '.join(extra)}.")
        errors.extend(_type_rules(kind, slide, where))
        if editorial and kind == previous and kind not in {"section"}:
            errors.append(f"Slide {number} repeats the {kind} type of the slide before it. Choose the type that fits the evidence, or merge the slides.")
        if kind == "table":
            tables += 1
            if editorial and tables == 3:
                errors.append(f"Slide {number} is the third table. Use at most two; show figures as kpis or a chart.")
        previous = kind
    return errors


def _section_names(deck: dict) -> List[str]:
    sections = deck.get("sections") if isinstance(deck.get("sections"), list) else []
    return [str(item.get("name")) for item in sections if isinstance(item, dict) and item.get("name")]


def _check_fields(value: dict, fields: Dict[str, dict], where: str, limits: bool = True) -> List[str]:
    errors = []
    for name, spec in fields.items():
        errors.extend(_check(value.get(name), spec, f"{where} {name}", limits))
    return errors


def _check(value, spec: dict, where: str, limits: bool = True) -> List[str]:
    if value is None or value == "" or value == []:
        if spec.get("required", True) and not (spec["kind"] == "list" and spec["low"] == 0):
            return [f"{where} is required."]
        return []
    kind = spec["kind"]
    if kind == "str":
        if not isinstance(value, (str, int, float)):
            return [f"{where} must be text."]
        text = re.sub(r"\*\*", "", str(value))
        if limits and len(text) > spec["limit"]:
            return [f"{where} is {len(text)} characters; the limit is {spec['limit']}."]
        return []
    if kind == "numbers":
        if not isinstance(value, list) or not value:
            return [f"{where} must be a list of numbers."]
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
            return [f"{where} must contain only plain numbers, without units or quotes."]
        return []
    if kind == "list":
        if not isinstance(value, list):
            return [f"{where} must be a list."]
        if not spec["low"] <= len(value) <= spec["high"]:
            return [f"{where} has {len(value)} entries; use {spec['low']} to {spec['high']}."]
        errors = []
        for index, item in enumerate(value, start=1):
            errors.extend(_check(item, spec["item"], f"{where} #{index}", limits))
        return errors
    if not isinstance(value, dict):
        return [f"{where} must be an object."]
    return _check_fields(value, spec["fields"], where, limits)


def _type_rules(kind: str, slide: dict, where: str) -> List[str]:
    errors = []
    if kind == "table":
        columns = slide.get("columns") or []
        for index, row in enumerate(slide.get("rows") or [], start=1):
            if isinstance(row, list) and len(row) != len(columns):
                errors.append(f"{where} row {index} has {len(row)} cells; it needs {len(columns)}, one per column.")
    if kind == "roadmap":
        periods = slide.get("periods") or []
        for lane in slide.get("lanes") or []:
            if isinstance(lane, dict) and isinstance(lane.get("cells"), list) and len(lane["cells"]) != len(periods):
                errors.append(f"{where} lane {lane.get('name')!r} needs one cell per period ({len(periods)}); use \"\" for an empty period.")
    if kind == "chart":
        if slide.get("chart_type") not in CHART_TYPES:
            errors.append(f"{where} chart_type must be one of: {', '.join(CHART_TYPES)}.")
        categories = slide.get("categories") or []
        for series in slide.get("series") or []:
            if isinstance(series, dict) and isinstance(series.get("values"), list) and len(series["values"]) != len(categories):
                errors.append(f"{where} series {series.get('name')!r} needs one value per category ({len(categories)}).")
    return errors


NUMBER = re.compile(r"(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?")


def _core(token: str) -> str:
    core = token.lstrip("$€£").replace(",", "")
    if "." in core:
        core = core.rstrip("0").rstrip(".")
    return core


def unsupported_figures(deck: dict, sources: str) -> List[str]:
    """Figures in the deck whose digits never appear in the sources or the request."""
    if not sources.strip():
        return []
    known = {_core(token) for token in NUMBER.findall(sources)}
    found: List[str] = []

    def consider(core: str) -> None:
        if not core or core in known or core in found:
            return
        if core.isdigit() and int(core) <= 12:
            return
        found.append(core)

    for text in _strings({"cover": deck.get("cover"), "slides": deck.get("slides")}):
        for token in NUMBER.findall(text):
            consider(_core(token))
    for slide in deck.get("slides") or []:
        if not isinstance(slide, dict):
            continue
        for series in slide.get("series") or []:
            for value in (series.get("values") or []) if isinstance(series, dict) else []:
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    consider(_core(repr(value)))
    return found[:12]


def _strings(value) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for key, item in value.items() if key not in {"type", "date"} for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def with_agenda(deck: dict) -> dict:
    """Decks with three or more sections get an agenda right after the executive summary."""
    slides = deck.get("slides")
    if not isinstance(slides, list) or len(slides) < 7 or len(_section_names(deck)) < 3:
        return deck
    if any(isinstance(slide, dict) and slide.get("type") == "agenda" for slide in slides):
        return deck
    position = 1 if slides and isinstance(slides[0], dict) and slides[0].get("type") == "executive_summary" else 0
    return {**deck, "slides": slides[:position] + [{"type": "agenda"}] + slides[position:]}


def section_number(deck: dict, name: str) -> int:
    names = _section_names(deck)
    return names.index(name) + 1 if name in names else 0


def apply_patch(deck: dict, patch: dict) -> Tuple[Optional[dict], str]:
    """Accept either a whole deck or {"replace": {"3": slide}} keyed by 1-based slide number."""
    if isinstance(patch.get("slides"), list):
        return patch, "deck"
    replacements = patch.get("replace")
    if not isinstance(replacements, dict):
        return None, "none"
    updated = json.loads(json.dumps(deck))
    for key, slide in replacements.items():
        try:
            index = int(key) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(updated["slides"]) and isinstance(slide, dict):
            updated["slides"][index] = slide
    for key in ("cover", "sections", "storyline"):
        if key in patch:
            updated[key] = patch[key]
    return updated, "patch"
