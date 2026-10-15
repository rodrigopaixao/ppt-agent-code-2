from pathlib import Path

from pptx import Presentation

from app.models.presentation import ContentBlock, LayoutName, PresentationSpec, SlideSpec
from app.pptx.builder import build_presentation
from app.pptx.inspector import inspect_template


def sample_spec() -> PresentationSpec:
    return PresentationSpec(
        title="Test deck",
        slides=[
            SlideSpec(layout=LayoutName.TITLE, title="Test deck", subtitle="A generated subtitle"),
            SlideSpec(
                layout=LayoutName.TITLE_CONTENT,
                title="Key findings",
                blocks=[ContentBlock(kind="bullets", items=["First finding", "Second finding"])],
                sources=["source.txt"],
            ),
            SlideSpec(
                layout=LayoutName.TWO_COLUMN,
                title="Comparison",
                blocks=[
                    ContentBlock(kind="bullets", heading="Before", items=["Manual"]),
                    ContentBlock(kind="bullets", heading="After", items=["Automated"]),
                ],
            ),
        ],
    )


def test_inspector_maps_semantic_layouts(synthetic_template: Path) -> None:
    result = inspect_template(synthetic_template)
    assert result["mapping"]["title"] == {"master": 0, "layout": 0}
    assert result["mapping"]["title_content"] == {"master": 0, "layout": 1}
    assert result["mapping"]["section"] == {"master": 0, "layout": 2}
    assert result["mapping"]["two_column"] == {"master": 0, "layout": 3}
    assert result["mapping"]["blank"] == {"master": 0, "layout": 6}


def test_builder_removes_examples_and_preserves_layouts(
    synthetic_template: Path, tmp_path: Path
) -> None:
    output = tmp_path / "result.pptx"
    build_presentation(synthetic_template, sample_spec(), output)

    generated = Presentation(output)
    assert len(generated.slides) == 3
    assert [slide.shapes.title.text for slide in generated.slides] == [
        "Test deck",
        "Key findings",
        "Comparison",
    ]
    assert "EXAMPLE SLIDE TO REMOVE" not in [
        shape.text
        for slide in generated.slides
        for shape in slide.shapes
        if hasattr(shape, "text")
    ]
    assert generated.slides[1].slide_layout.name == "Title and Content"
    assert generated.slides[2].slide_layout.name == "Two Column Comparison"
