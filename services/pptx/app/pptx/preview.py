import html
import shutil
import subprocess
from pathlib import Path
from typing import List

from app.models.presentation import PresentationSpec


def render_with_libreoffice(pptx_path: Path, output_dir: Path) -> List[Path]:
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    pdftoppm = shutil.which("pdftoppm")
    if not soffice or not pdftoppm:
        return []
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(pptx_path)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    pdf_path = output_dir / f"{pptx_path.stem}.pdf"
    prefix = output_dir / "slide"
    subprocess.run(
        [pdftoppm, "-png", "-r", "110", str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return sorted(output_dir.glob("slide-*.png"))


def render_svg_fallback(spec: PresentationSpec, output_dir: Path) -> List[Path]:
    paths: List[Path] = []
    for index, slide in enumerate(spec.slides, start=1):
        title = html.escape(slide.title)
        content = []
        for block in slide.blocks:
            content.extend(block.items or ([block.text] if block.text else []))
        rows = []
        for row, item in enumerate(content[:6]):
            rows.append(
                f'<text x="100" y="{210 + row * 54}" font-size="24" fill="#2f3c37">'
                f"• {html.escape(item[:110])}</text>"
            )
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">
<rect width="1280" height="720" fill="#f9f8f4"/>
<rect width="20" height="720" fill="#c6382d"/>
<text x="90" y="115" font-family="Georgia,serif" font-size="45" fill="#12211b">{title}</text>
<line x1="90" y1="145" x2="1180" y2="145" stroke="#d8ddd9"/>
{''.join(rows)}
<text x="1160" y="675" font-family="sans-serif" font-size="18" fill="#68736e">{index}</text>
</svg>"""
        path = output_dir / f"slide-{index}.svg"
        path.write_text(svg, encoding="utf-8")
        paths.append(path)
    return paths


def render_previews(pptx_path: Path, spec: PresentationSpec, output_dir: Path) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("slide-*"):
        old.unlink()
    try:
        rendered = render_with_libreoffice(pptx_path, output_dir)
        if rendered:
            return rendered
    except (OSError, subprocess.SubprocessError):
        pass
    return render_svg_fallback(spec, output_dir)
