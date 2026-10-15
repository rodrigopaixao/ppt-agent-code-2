from pathlib import Path

from app.models.presentation import ContentBlock, LayoutName, PresentationSpec, SlideSpec
from app.pptx.preview import render_svg_fallback


def test_svg_preview_is_created_and_escapes_content(tmp_path: Path) -> None:
    spec = PresentationSpec(
        title="Preview",
        slides=[
            SlideSpec(
                layout=LayoutName.TITLE_CONTENT,
                title="A < B",
                blocks=[ContentBlock(items=["Safe & visible"])],
            )
        ],
    )
    paths = render_svg_fallback(spec, tmp_path)
    content = paths[0].read_text(encoding="utf-8")
    assert paths[0].name == "slide-1.svg"
    assert "A &lt; B" in content
    assert "Safe &amp; visible" in content
