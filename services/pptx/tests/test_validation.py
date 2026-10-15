import pytest
from pydantic import ValidationError

from app.models.presentation import ContentBlock, LayoutName, PresentationSpec, SlideSpec


def test_rejects_overlong_bullet() -> None:
    with pytest.raises(ValidationError):
        ContentBlock(items=["x" * 241])


def test_rejects_dense_slide() -> None:
    with pytest.raises(ValidationError):
        SlideSpec(
            layout=LayoutName.TITLE_CONTENT,
            title="Too much",
            blocks=[ContentBlock(items=["x" * 200 for _ in range(8)])],
        )


def test_valid_spec_serializes_layout_as_string() -> None:
    spec = PresentationSpec(
        title="Valid",
        slides=[SlideSpec(layout=LayoutName.TITLE, title="Valid")],
    )
    assert spec.model_dump(mode="json")["slides"][0]["layout"] == "title"
