"""PDF text extraction and file conversion."""

from __future__ import annotations

from pathlib import Path

import fitz


class Pdf2mdError(Exception):
    """Domain error for pdf2md conversion failures."""


def extract_text(path: Path) -> str:
    """Extract plain text from a PDF page by page (PyMuPDF)."""
    path = Path(path)

    try:
        with path.open("rb") as f:
            header = f.read(4)
    except OSError as e:
        raise Pdf2mdError(f"读取文件头失败: {e}") from e

    if header != b"%PDF":
        raise Pdf2mdError(
            f"文件不是有效的 PDF 格式（缺少 PDF 文件头签名）: {path}"
        )

    try:
        parts: list[str] = []
        with fitz.open(path) as doc:
            for page in doc:
                parts.append(page.get_text("text"))
        return "\n\n".join(parts)
    except Exception as e:  # noqa: BLE001 — surface PyMuPDF failures as domain errors
        raise Pdf2mdError(f"PDF 解析失败: {e}") from e


def convert(input_path: Path, output_path: Path) -> dict:
    """Extract PDF text and write it to output_path. Returns a result dict."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    text = extract_text(input_path)

    try:
        if output_path.parent and str(output_path.parent) not in ("", "."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise Pdf2mdError(f"写入输出文件失败: {e}") from e

    return {
        "ok": True,
        "input": str(input_path),
        "output": str(output_path),
        "chars": len(text),
    }
