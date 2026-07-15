"""Local parse first; fall back to MinerU OCR when text is insufficient."""

from __future__ import annotations

from pathlib import Path

from pdf2md.config import load_mineru_config
from pdf2md.core import Pdf2mdError, extract_text_local
from pdf2md.mineru import MinerUError, parse_pdf
from pdf2md.quality import (
    format_pdf_insufficient_reason,
    is_pdf_text_insufficient,
    pdf_page_stats,
)


def extract_text(
    path: Path,
    *,
    ocr: bool = True,
    force_ocr: bool = False,
) -> tuple[str, dict]:
    """Extract Markdown from PDF with optional MinerU OCR fallback.

    Returns ``(text, meta)`` where meta contains ``parser`` and optionally
    ``fallback_reason``.

    - ``ocr=True`` (default): local first; OCR if text looks insufficient.
    - ``ocr=False``: local only (``--no-ocr``).
    - ``force_ocr=True``: skip local quality check, always MinerU (``--force-ocr``).
    """
    path = Path(path)

    if force_ocr:
        return _run_mineru(path, fallback_reason="force_ocr")

    local_text = extract_text_local(path)
    if not ocr:
        return local_text, {"parser": "local"}

    page_count, scanned_ratio = pdf_page_stats(path)
    if not is_pdf_text_insufficient(local_text, page_count, scanned_ratio):
        return local_text, {"parser": "local"}

    reason = format_pdf_insufficient_reason(local_text, page_count, scanned_ratio)
    return _run_mineru(path, fallback_reason=reason)


def _run_mineru(path: Path, fallback_reason: str) -> tuple[str, dict]:
    try:
        config = load_mineru_config()
    except ValueError as e:
        raise Pdf2mdError(f"PDF 需要 OCR（{fallback_reason}），但 {e}") from e

    try:
        md = parse_pdf(path, config)
    except MinerUError as e:
        raise Pdf2mdError(f"MinerU OCR 失败: {e}") from e

    return md, {
        "parser": "mineru_vlm_ocr",
        "fallback_reason": fallback_reason,
    }
