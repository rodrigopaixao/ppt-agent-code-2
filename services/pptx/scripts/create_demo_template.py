"""Create a synthetic template for local development. It contains no client material."""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "assets" / "templates" / "client-a-template.pptx"


def main() -> None:
    presentation = Presentation()
    names = {
        0: "Title Slide",
        1: "Title and Content",
        2: "Section Divider",
        3: "Two Column Comparison",
        6: "Blank",
    }
    for index, name in names.items():
        presentation.slide_layouts[index].name = name

    # A sample slide demonstrates that generated decks remove template examples.
    sample = presentation.slides.add_slide(presentation.slide_layouts[0])
    sample.shapes.title.text = "Synthetic Development Template"
    sample.placeholders[1].text = "Replace with an authorized template before real use"
    accent = sample.shapes.add_shape(1, 0, 0, Inches(0.18), presentation.slide_height)
    accent.fill.solid()
    accent.fill.fore_color.rgb = RGBColor(198, 56, 45)
    accent.line.fill.background()
    for paragraph in sample.shapes.title.text_frame.paragraphs:
        paragraph.font.name = "Aptos Display"
        paragraph.font.size = Pt(32)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    presentation.save(OUTPUT)
    print(f"Created synthetic template at {OUTPUT}")


if __name__ == "__main__":
    main()
