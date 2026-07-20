"""Pinned, embedded fonts for deterministic layout (Analysis 0012 finding 9.3).

Word-wrap uses the renderer's own string-width metrics, so those metrics
must not depend on the environment: we register Bitstream Vera from
reportlab's own bundled copy (frozen upstream since 2003) and embed it in
the output PDF. No system-font lookup ever happens, and the device renders
the exact glyphs the manifest was measured against.
"""

from __future__ import annotations

from pathlib import Path

from .geometry import SCALE

BODY = "InkVera"
BOLD = "InkVera-Bold"
ITALIC = "InkVera-Italic"

_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts_dir = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont(BODY, str(fonts_dir / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD, str(fonts_dir / "VeraBd.ttf")))
    pdfmetrics.registerFont(TTFont(ITALIC, str(fonts_dir / "VeraIt.ttf")))
    _registered = True


def width_px(text: str, font: str, size_pt: float) -> float:
    """Rendered width of text in device pixels."""
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(text, font, size_pt) / SCALE
