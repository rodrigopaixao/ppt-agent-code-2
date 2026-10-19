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
    for name in ("executive_summary", "kpis", "cards", "process", "roadmap", "table", "chart", "comparison", "rows"):
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
