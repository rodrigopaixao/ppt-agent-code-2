import asyncio
import copy
import json
import shutil
from pathlib import Path

import pytest
from pptx import Presentation

from app.agent.deckspec import apply_patch, catalog, structure_errors, unsupported_figures, with_agenda
from app.agent.pipeline import run_pipeline
from app.agent.renderer import build
from app.agent.textfit import Para, fit, runs, wrap

FIXTURE = Path(__file__).parent / "fixtures" / "sample_deck.json"
REPOSITORY = next(
    iter(sorted((Path(__file__).resolve().parents[3] / "assets" / "templates").glob("*epository*.pptx"))),
    None,
)


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_wrap_and_fit_shrink_before_failing() -> None:
    lines = wrap("one two three four five six seven eight nine ten", 1.0, 12)
    assert len(lines) > 1
    short = fit([Para("A short line", 14)], 4.0, 0.5, 10)
    assert short.ok and short.shrink == 0
    long = fit([Para("word " * 200, 14)], 2.0, 0.5, 10)
    assert not long.ok and long.ratio > 1


def test_bold_markup_becomes_runs() -> None:
    assert runs("Grew **9.6%** in 2025") == [("Grew ", False), ("9.6%", True), (" in 2025", False)]


def test_sample_deck_is_valid_and_catalog_lists_every_type() -> None:
    assert structure_errors(sample()) == []
    text = catalog()
    for name in ("executive_summary", "kpis", "cards", "process", "roadmap", "table", "chart", "comparison", "rows", "strategy_house"):
        assert f"### {name}" in text


def test_structure_errors_are_specific() -> None:
    deck = sample()
    deck["slides"][4]["rows"][0] = ["only", "three", "cells"]
    deck["slides"][5]["type"] = "table"
    deck["slides"][2]["section"] = "Unknown"
    errors = " ".join(structure_errors(deck))
    assert "row 1 has 3 cells" in errors
    assert "Slide 6 repeats the table type" in errors
    assert "Slide 3 (kpis) section must exactly match" in errors


def test_deck_must_open_with_executive_summary_and_gets_an_agenda() -> None:
    deck = sample()
    deck["slides"] = deck["slides"][1:]
    assert any("Slide 1 must be the executive_summary" in error for error in structure_errors(deck))

    deck = sample()
    deck["slides"] = [slide for slide in deck["slides"] if slide["type"] != "agenda"]
    with_agenda_deck = with_agenda(deck)
    assert [slide["type"] for slide in with_agenda_deck["slides"][:2]] == ["executive_summary", "agenda"]
    assert with_agenda(with_agenda_deck) == with_agenda_deck


def test_unsupported_figures_flags_invented_numbers() -> None:
    deck = sample()
    sources = json.dumps(deck)
    assert unsupported_figures(deck, sources) == []
    deck["slides"][2]["items"][0]["value"] = "$14.5B"
    assert "14.5" in unsupported_figures(deck, sources)


def test_patch_replaces_numbered_slides() -> None:
    deck = sample()
    replacement = copy.deepcopy(deck["slides"][0])
    replacement["headline"] = "A new headline"
    updated, mode = apply_patch(deck, {"replace": {"1": replacement}})
    assert mode == "patch" and updated["slides"][0]["headline"] == "A new headline"
    assert deck["slides"][0]["headline"] != "A new headline"


def test_build_on_generic_template(tmp_path: Path, synthetic_template: Path) -> None:
    output = tmp_path / "deck.pptx"
    build(synthetic_template, sample(), output)
    assert len(Presentation(str(output)).slides) == len(sample()["slides"]) + 1


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
def test_build_on_repository_template_fits_and_removes_examples(tmp_path: Path) -> None:
    output = tmp_path / "deck.pptx"
    problems = build(REPOSITORY, sample(), output)
    assert problems == []
    presentation = Presentation(str(output))
    assert len(presentation.slides) == len(sample()["slides"]) + 1
    second = presentation.slides[1]
    assert second.shapes.title.text_frame.text.startswith("Summary | ")


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
def test_build_reports_text_that_cannot_fit(tmp_path: Path) -> None:
    deck = sample()
    deck["slides"][5]["items"][0]["points"] = ["A very long point that keeps going " * 4] * 4
    problems = build(REPOSITORY, deck, tmp_path / "deck.pptx")
    assert any(problem.startswith("Slide 6 (cards) card 1 points") for problem in problems)


def strategy_house(slide: dict, points: bool) -> dict:
    pillars = [
        {"heading": "Digital-first advice", "points": ["Guided journeys in the app", "Advisers on video when needed"]},
        {"heading": "Simple, fair pricing", "points": ["One fee schedule across channels"]},
        {"heading": "Connected client data", "points": ["Single client view for every team", "Real-time next best action"]},
        {"heading": "Faster delivery", "points": ["Quarterly releases moving to monthly"]},
    ]
    if not points:
        pillars = [{"heading": pillar["heading"]} for pillar in pillars]
    return {
        "type": "strategy_house",
        "section": slide["section"],
        "label": "Strategy",
        "headline": "Four pillars deliver the digital ambition, built on shared data and delivery foundations",
        "aspiration": "Be the primary digital partner for our clients…",
        "pillars": pillars,
        "outcome": "…to drive sustainable, profitable growth",
    }


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
@pytest.mark.parametrize("points", [True, False])
def test_strategy_house_fits_and_every_part_is_editable(tmp_path: Path, points: bool) -> None:
    deck = sample()
    deck["slides"][5] = strategy_house(deck["slides"][5], points)
    assert structure_errors(deck) == []
    regions: list = []
    assert build(REPOSITORY, deck, tmp_path / "deck.pptx", regions) == []
    paths = {tuple(para["path"]) for region in regions if region["slide"] == 6 for para in region["paras"]}
    assert {("slides", 5, "aspiration"), ("slides", 5, "outcome"), ("slides", 5, "pillars", 3, "heading")} <= paths
    assert (("slides", 5, "pillars", 0, "points", 1) in paths) == points


def journey(slide: dict) -> dict:
    hand_off = {"title": "Hand-off", "text": "**Appointment booking** or **on-demand support** offered in the app", "via": "Digital self-serve (mobile / web)"}
    adviser = {"title": "Adviser", "text": "**Video or branch** adviser completes the request", "via": "Video or in person"}
    return {
        "type": "journey",
        "section": slide["section"],
        "label": "Hand-offs",
        "headline": "Digital entry points need a clear hand-off to advisers for clients with complex needs",
        "subheader": "Inbound client journey map",
        "lanes": [
            {"name": "Simple needs", "description": "Little information needed, short tasks", "highlight": "4", "steps": [
                {"title": "Research", "text": "**Digital discovery** of simple products and services"},
                {"title": "Self-serve", "text": "Client **completes the task digitally** without help", "via": "Digital self-serve (mobile / web)"},
                {"title": "Support needed", "text": "Client **needs a person** and cannot finish digitally", "via": "Digital self-serve (mobile / web)"},
                hand_off,
                adviser,
            ]},
            {"name": "Complex needs", "highlight": "2", "steps": [{"title": "Research", "text": "**Digital discovery** of complex products"}, hand_off, adviser]},
        ],
    }


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
def test_journey_fits_and_every_part_is_editable(tmp_path: Path) -> None:
    deck = sample()
    deck["slides"][5] = journey(deck["slides"][5])
    assert structure_errors(deck) == []
    regions: list = []
    assert build(REPOSITORY, deck, tmp_path / "deck.pptx", regions) == []
    paths = {tuple(para["path"]) for region in regions if region["slide"] == 6 for para in region["paras"]}
    expected = {
        ("slides", 5, "lanes", 0, "name"),
        ("slides", 5, "lanes", 0, "description"),
        ("slides", 5, "lanes", 0, "steps", 4, "text"),
        ("slides", 5, "lanes", 1, "steps", 2, "via"),
        ("slides", 5, "lanes", 1, "steps", 0, "title"),
    }
    assert expected <= paths


def test_journey_highlight_must_name_a_step() -> None:
    deck = sample()
    deck["slides"][5] = journey(deck["slides"][5])
    deck["slides"][5]["lanes"][1]["highlight"] = "4"
    assert any("lanes #2 highlight must be a step number from 1 to 3" in error for error in structure_errors(deck))


def timeline(slide: dict) -> dict:
    return {
        "type": "timeline",
        "section": slide["section"],
        "label": "Plan",
        "headline": "Platform migration completes by late September, with three steering checkpoints",
        "start": "2026-06-15",
        "end": "2026-09-25",
        "milestones": [
            {"date": "2026-06-19", "label": "Business case approved"},
            {"date": "2026-07-06", "end": "2026-07-17", "label": "Vendor proposals due", "kind": "submission"},
            {"date": "2026-07-20", "end": "2026-08-07", "label": "Security review", "kind": "review"},
            {"date": "2026-08-14", "label": "Pilot go-live"},
            {"date": "2026-09-21", "label": "Full cut-over"},
        ],
        "deliverables": [
            {"date": "2026-06-26", "label": "Target architecture"},
            {"date": "2026-08-21", "label": "Pilot results report"},
        ],
        "meeting_name": "SteerCo",
        "meetings": [
            {"date": "2026-07-03", "title": "Mobilisation", "points": ["Confirm scope and budget", "Agree vendor shortlist"]},
            {"date": "2026-08-12", "title": "Pilot readiness", "points": ["Review security findings", "Approve pilot go-live"]},
            {"date": "2026-09-16", "title": "Cut-over decision", "points": ["Pilot results and lessons", "Go or no-go for cut-over"]},
        ],
    }


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
def test_timeline_fits_and_every_part_is_editable(tmp_path: Path) -> None:
    deck = sample()
    deck["slides"][5] = timeline(deck["slides"][5])
    assert structure_errors(deck) == []
    regions: list = []
    assert build(REPOSITORY, deck, tmp_path / "deck.pptx", regions) == []
    paths = {tuple(para["path"]) for region in regions if region["slide"] == 6 for para in region["paras"]}
    expected = {
        ("slides", 5, "milestones", 2, "label"),
        ("slides", 5, "deliverables", 1, "label"),
        ("slides", 5, "meetings", 0, "title"),
        ("slides", 5, "meetings", 2, "points", 1),
        ("slides", 5, "milestones_heading"),
    }
    assert expected <= paths


@pytest.mark.skipif(REPOSITORY is None, reason="The slide repository template is not available.")
def test_timeline_reports_labels_too_crowded_to_fit(tmp_path: Path) -> None:
    deck = sample()
    deck["slides"][5] = timeline(deck["slides"][5])
    deck["slides"][5]["milestones"][3:4] = [
        {"date": "2026-08-12", "label": "Pilot go-live"},
        {"date": "2026-08-13", "label": "Infrastructure provisioning"},
        {"date": "2026-08-14", "label": "Environment accreditation"},
    ]
    problems = build(REPOSITORY, deck, tmp_path / "deck.pptx")
    assert any("milestones 5 label: its date is too close" in problem for problem in problems)


def test_timeline_dates_are_checked() -> None:
    deck = sample()
    deck["slides"][5] = timeline(deck["slides"][5])
    slide = deck["slides"][5]
    slide["milestones"][0]["date"] = "June 19"
    slide["milestones"][1]["end"] = "2026-10-02"
    slide["milestones"][3]["kind"] = "deadline"
    slide["meetings"][0]["date"] = "2026-06-01"
    errors = " ".join(structure_errors(deck))
    assert "milestones #1 date must be a date written YYYY-MM-DD" in errors
    assert "milestones #2 end 2026-10-02 falls after the calendar end" in errors
    assert "milestones #4 kind must be one of" in errors
    assert "meetings #1 date 2026-06-01 falls outside start to end" in errors

    slide = timeline(deck["slides"][4])
    slide["end"] = "2027-03-01"
    deck["slides"][5] = slide
    assert any("26 weeks" in error for error in structure_errors(deck))


def test_unsupported_figures_flags_invented_dates() -> None:
    deck = sample()
    sources = json.dumps(deck) + (
        " Business case approval on June 19th, proposals due 6 July to 7/17. Security review 20 July to Aug 7. "
        "Pilot go-live 08/14 and cut-over September 21. Architecture by June 26 and pilot report by 21 August. "
        "SteerCo meetings on July 3, August 12 and September 16."
    )
    deck["slides"][5] = timeline(deck["slides"][5])
    assert unsupported_figures(deck, sources) == []
    deck["slides"][5]["meetings"][1]["date"] = "2026-08-13"
    assert "2026-08-13" in unsupported_figures(deck, sources)


class ScriptedModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def __call__(self, system, prompt, resume=None, images=()):
        self.calls.append({"system": system, "prompt": prompt, "resume": resume, "images": list(images)})
        return self.replies.pop(0), "session-1"


def workspace_for(tmp_path: Path, template: Path) -> Path:
    workspace = tmp_path / "work"
    workspace.mkdir()
    shutil.copy(template, workspace / "template.pptx")
    deck = sample()
    (workspace / "sources.md").write_text(json.dumps(deck), encoding="utf-8")
    return workspace


def test_pipeline_fixes_overflow_then_applies_review(tmp_path: Path, synthetic_template: Path) -> None:
    template = REPOSITORY or synthetic_template
    workspace = workspace_for(tmp_path, template)
    draft = sample()
    draft["slides"][2]["items"][0]["value"] = "$99.9B"
    fixed_slide = sample()["slides"][2]
    reviewed_slide = copy.deepcopy(sample()["slides"][0])
    reviewed_slide["headline"] = "Reviewed headline that states the answer"
    model = ScriptedModel(
        [
            json.dumps(draft),
            json.dumps({"replace": {"3": fixed_slide}}),
            json.dumps({"verdict": "revise", "issues": [{"slide": 1, "problem": "Vague", "fix": "Sharpen the headline"}]}),
            json.dumps({"replace": {"1": reviewed_slide}}),
        ]
    )
    events = []
    images = [workspace / "previews" / "slide-01.png"]
    session = asyncio.run(
        run_pipeline(workspace, {"prompt": "Make a deck"}, events.append, ask=model, render=lambda _workspace: images)
    )
    assert session == "session-1"
    saved = json.loads((workspace / "deck.json").read_text(encoding="utf-8"))
    assert saved["slides"][2]["items"][0]["value"] == "$9.5B"
    assert saved["slides"][0]["headline"] == "Reviewed headline that states the answer"
    assert "99.9" in model.calls[1]["prompt"]
    assert [path for _label, path in model.calls[2]["images"]] == images
    assert model.calls[2]["images"][0][0].startswith("Image of slide 0: cover")
    assert (workspace / "presentation.pptx").exists()


def test_pipeline_revision_uses_existing_deck(tmp_path: Path, synthetic_template: Path) -> None:
    workspace = workspace_for(tmp_path, REPOSITORY or synthetic_template)
    (workspace / "deck.json").write_text(json.dumps(sample()), encoding="utf-8")
    changed = copy.deepcopy(sample()["slides"][0])
    changed["label"] = "Answer"
    model = ScriptedModel([json.dumps({"replace": {"1": changed}})])
    request = {"prompt": "Make a deck", "revision": "Rename the summary label", "resume": "session-0"}
    asyncio.run(run_pipeline(workspace, request, lambda _event: None, ask=model, render=lambda _workspace: []))
    assert model.calls[0]["resume"] == "session-0"
    assert "Rename the summary label" in model.calls[0]["prompt"]
    saved = json.loads((workspace / "deck.json").read_text(encoding="utf-8"))
    assert saved["slides"][0]["label"] == "Answer"
