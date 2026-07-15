"""Heuristics for deciding when local PDF text is insufficient (need OCR)."""

from __future__ import annotations

from pathlib import Path

import fitz

PDF_MIN_TOTAL_CHARS = 50
PDF_MIN_CHARS_PER_PAGE = 20.0
PDF_SCANNED_IMAGE_MIN_BYTES = 5000
PDF_SCANNED_RATIO_THRESHOLD = 0.3


def pdf_page_stats(path: Path) -> tuple[int, float]:
    """Return (page_count, scanned_page_ratio).

    A page is "scanned" if it has at least one image block whose compressed
    size exceeds PDF_SCANNED_IMAGE_MIN_BYTES.
    """
    path = Path(path)
    try:
        with fitz.open(path) as doc:
            total = doc.page_count
            if total <= 0:
                return 0, 0.0
            scanned = 0
            for page in doc:
                if _page_has_large_image(page):
                    scanned += 1
            return total, scanned / total
    except Exception:  # noqa: BLE001 — treat unreadable PDF as unknown stats
        return 0, 0.0


def _page_has_large_image(page: fitz.Page) -> bool:
    try:
        for info in page.get_image_info():
            size = info.get("size") or 0
            if isinstance(size, (int, float)) and size > PDF_SCANNED_IMAGE_MIN_BYTES:
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def is_pdf_text_insufficient(text: str, page_count: int, scanned_ratio: float) -> bool:
    trimmed = text.strip()
    length = len(trimmed)

    if not trimmed:
        return True
    if length < PDF_MIN_TOTAL_CHARS:
        return True
    if page_count > 0 and (length / page_count) < PDF_MIN_CHARS_PER_PAGE:
        return True
    if scanned_ratio > PDF_SCANNED_RATIO_THRESHOLD:
        return True
    return False


def format_pdf_insufficient_reason(text: str, page_count: int, scanned_ratio: float) -> str:
    if scanned_ratio > PDF_SCANNED_RATIO_THRESHOLD:
        scanned_pages = round(scanned_ratio * page_count)
        return (
            f"scanned_image_pages: {scanned_pages}/{page_count} "
            f"({scanned_ratio * 100:.1f}%)"
        )
    length = len(text.strip())
    if page_count > 0:
        return (
            f"insufficient_text: {length} chars / {page_count} pages "
            f"({length / page_count:.1f} chars/page)"
        )
    return f"insufficient_text: {length} chars"
