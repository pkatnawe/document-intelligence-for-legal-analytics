"""Document handling — read one invoice document.

The extraction service assumes **one document = one invoice**. Splitting a file that holds
several invoices into separate single-invoice documents is an *ingestion* concern handled
upstream (see `app/documents/splitter.py`), so this loader keeps a clean job.

It detects whether a PDF has a *usable* text layer. Digital PDFs return text for the
text-LLM path. PDFs that are scans — or whose text layer is corrupt/encoded (common with
real documents) — have no usable text, so each page is rendered to PNG for the vision
model. This covers failure case (b): image-only scans, and the real-world garbled-text case.

PyMuPDF (fitz) does both text extraction and rendering with no external system dependency
(no poppler).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

import fitz  # PyMuPDF

# Characters we'd expect in a real invoice's text. A low ratio of these signals a
# corrupt/encoded text layer (control characters, custom glyph encodings).
_TEXTY = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \n\t.,:;/$%#-()&@'\""
)


@dataclass
class LoadedDoc:
    has_text: bool
    text: str = ""
    page_images_png: list[bytes] = field(default_factory=list)  # densest page first


def _looks_like_text(s: str, min_chars: int, min_ratio: float) -> bool:
    s = s.strip()
    if len(s) < min_chars:
        return False
    good = sum(1 for ch in s if ch in _TEXTY)
    return good / len(s) >= min_ratio


def _ink_ratio(pix) -> float:
    """Fraction of non-white bytes — a cheap proxy for how much content a page has."""
    data = pix.samples
    return 0.0 if not data else 1.0 - (data.count(255) / len(data))


def load_pdf(data: bytes, min_chars: int = 20, min_text_ratio: float = 0.6, dpi: int = 200) -> LoadedDoc:
    """Return a usable text layer if present; otherwise render page images for the VLM,
    densest (most content) page first so blank cover/trailer pages don't lead."""
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        text = "\n".join(page.get_text() for page in doc)
        if _looks_like_text(text, min_chars, min_text_ratio):
            return LoadedDoc(has_text=True, text=text)

        scored = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            scored.append((_ink_ratio(pix), pix.tobytes("png")))
        scored.sort(key=lambda x: x[0], reverse=True)
        images = [png for ink, png in scored if ink > 0.002] or [scored[0][1]]
        return LoadedDoc(has_text=False, page_images_png=images)
    finally:
        doc.close()


def png_to_data_uri(png: bytes) -> str:
    """Encode PNG bytes as a data URI for a vision model input field."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
