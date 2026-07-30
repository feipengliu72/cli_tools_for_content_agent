"""OCR-first strategy; fall back to local parsing when OCR fails."""

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
    output_dir: Path | None = None,
) -> tuple[str, dict]:
    """Extract Markdown from PDF with OCR-first fallback strategy.

    Returns ``(text, meta)`` where meta contains ``parser`` and optionally
    ``fallback_reason``.

    - Default: MinerU OCR first; fall back to local PyMuPDF on OCR error.
    - ``ocr=False``: local only (``--no-ocr``).
    - ``output_dir``: if set, MinerU ZIP images are extracted to
      ``<output_dir>/images/``.

    Raises Pdf2mdError when OCR fails and local extraction is also
    insufficient.
    """
    path = Path(path)

    if not ocr:
        local_text = extract_text_local(path)
        _ensure_local_quality(local_text, path, ocr_attempted=False)
        return local_text, {"parser": "local"}

    # --- OCR-first strategy ------------------------------------------------
    try:
        return _run_mineru(path, output_dir=output_dir)
    except Pdf2mdError:
        # MinerU failed → fall back to local; error if local is also bad.
        local_text = extract_text_local(path)
        _ensure_local_quality(local_text, path, ocr_attempted=True)
        return local_text, {
            "parser": "local",
            "fallback_reason": "ocr_failed_fallback_to_local",
        }


def _ensure_local_quality(
    text: str, path: Path, *, ocr_attempted: bool
) -> None:
    """Raise Pdf2mdError when local extraction yields insufficient text."""
    page_count, scanned_ratio = pdf_page_stats(path)
    if is_pdf_text_insufficient(text, page_count, scanned_ratio):
        reason = format_pdf_insufficient_reason(text, page_count, scanned_ratio)
        suffix = "，OCR 也不可用" if ocr_attempted else ""
        raise Pdf2mdError(f"本地解析文本不足 ({reason}){suffix}")


def _run_mineru(
    path: Path,
    output_dir: Path | None = None,
) -> tuple[str, dict]:
    try:
        config = load_mineru_config()
    except ValueError as e:
        raise Pdf2mdError(f"MinerU 配置错误: {e}") from e
    try:
        md = parse_pdf(path, config, output_dir=output_dir)
    except MinerUError as e:
        raise Pdf2mdError(f"MinerU OCR 失败: {e}") from e
    return md, {"parser": "mineru_vlm_ocr"}
