from pathlib import Path

import pytest
from pptx import Presentation


@pytest.fixture
def synthetic_template(tmp_path: Path) -> Path:
    path = tmp_path / "synthetic-template.pptx"
    presentation = Presentation()
    presentation.slide_layouts[0].name = "Title Slide"
    presentation.slide_layouts[1].name = "Title and Content"
    presentation.slide_layouts[2].name = "Section Divider"
    presentation.slide_layouts[3].name = "Two Column Comparison"
    presentation.slide_layouts[6].name = "Blank"
    example = presentation.slides.add_slide(presentation.slide_layouts[0])
    example.shapes.title.text = "EXAMPLE SLIDE TO REMOVE"
    presentation.save(path)
    return path
