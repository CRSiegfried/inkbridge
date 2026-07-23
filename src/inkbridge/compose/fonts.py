"""Pinned, embedded fonts for deterministic layout.

Word-wrap uses the renderer's own string-width metrics, so those metrics
must not depend on the environment: we register Bitstream Vera (frozen
upstream since 2003) and embed it in the output PDF. Body/bold/italic/
bold-italic come from reportlab's bundled copies; the mono face is vendored
here (fonts/VeraMono.ttf, same 1.10 upstream release — reportlab does not
ship it; license in fonts/VERA-COPYRIGHT.TXT). No system-font lookup ever
happens, and the device renders the exact glyphs the manifest was measured
against.
"""

from __future__ import annotations

from pathlib import Path

from .geometry import SCALE

BODY = "InkVera"
BOLD = "InkVera-Bold"
ITALIC = "InkVera-Italic"
BOLDITALIC = "InkVera-BoldItalic"
MONO = "InkVera-Mono"

_registered = False


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    rl_fonts = Path(reportlab.__file__).parent / "fonts"
    own_fonts = Path(__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont(BODY, str(rl_fonts / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD, str(rl_fonts / "VeraBd.ttf")))
    pdfmetrics.registerFont(TTFont(ITALIC, str(rl_fonts / "VeraIt.ttf")))
    pdfmetrics.registerFont(TTFont(BOLDITALIC, str(rl_fonts / "VeraBI.ttf")))
    pdfmetrics.registerFont(TTFont(MONO, str(own_fonts / "VeraMono.ttf")))
    _registered = True


def width_px(text: str, font: str, size_pt: float) -> float:
    """Rendered width of text in device pixels."""
    from reportlab.pdfbase import pdfmetrics

    return pdfmetrics.stringWidth(text, font, size_pt) / SCALE
