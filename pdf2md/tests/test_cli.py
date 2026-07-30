"""Tests for pdf2md CLI and core."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest
from typer.testing import CliRunner

from pdf2md.cli import app
from pdf2md.config import load_mineru_config
from pdf2md.core import Pdf2mdError, convert, extract_text
from pdf2md.mineru import extract_full_md_from_zip
from pdf2md.quality import is_pdf_text_insufficient

runner = CliRunner()


def _make_pdf(path: Path, text: str = "Hello PDF") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def _make_emptyish_pdf(path: Path) -> Path:
    """PDF with almost no extractable text (blank page)."""
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


def test_extract_text_rejects_non_pdf(tmp_path: Path) -> None:
    fake = tmp_path / "not.pdf"
    fake.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(Pdf2mdError, match="不是有效的 PDF"):
        extract_text(fake)


def test_convert_writes_file_and_json_fields(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "sample.pdf",
                    "Page one content that is long enough to pass the local quality check here")
    out = tmp_path / "out" / "sample.md"

    result = convert(pdf, out, ocr=False)

    assert result["ok"] is True
    assert result["input"] == str(pdf)
    assert result["output"] == str(out)
    assert result["chars"] > 0
    assert result["parser"] == "local"
    assert out.exists()
    assert "Page one" in out.read_text(encoding="utf-8")


def test_cli_success_prints_json(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "cli.pdf",
                    "CLI text with enough characters here to pass the local quality check")
    out = tmp_path / "cli.md"

    result = runner.invoke(
        app,
        ["--input", str(pdf), "--output", str(out), "--no-ocr"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["output"] == str(out)
    assert payload["parser"] == "local"
    assert out.exists()


def test_cli_missing_options_fails() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code != 0


def test_cli_invalid_pdf_fails(tmp_path: Path) -> None:
    fake = tmp_path / "bad.pdf"
    fake.write_bytes(b"XXXX")
    out = tmp_path / "out.md"

    result = runner.invoke(
        app,
        ["--input", str(fake), "--output", str(out), "--no-ocr"],
    )

    assert result.exit_code == 1
    assert "不是有效的 PDF" in result.stderr
    assert not out.exists()



def test_is_pdf_text_insufficient_thresholds() -> None:
    assert is_pdf_text_insufficient("", 1, 0.0) is True
    assert is_pdf_text_insufficient("x" * 10, 1, 0.0) is True
    assert is_pdf_text_insufficient("x" * 100, 10, 0.0) is True  # 10 chars/page
    assert is_pdf_text_insufficient("x" * 100, 2, 0.0) is False
    assert is_pdf_text_insufficient("x" * 1000, 2, 0.5) is True


def test_load_mineru_config_from_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "providers": {
                    "mineru": {
                        "api_key": "tok-123",
                        "api_base": "https://example.test",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = load_mineru_config(cfg)
    assert loaded.api_key == "tok-123"
    assert loaded.api_base == "https://example.test"


def test_load_mineru_config_missing_key(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {"mineru": {"api_key": ""}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="api_key"):
        load_mineru_config(cfg)


def test_extract_full_md_from_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nested/dir/full.md", "# deep")
        zf.writestr("full.md", "# root")
    md = extract_full_md_from_zip(buf.getvalue())
    assert md == "# root"


def test_convert_ocr_fallback_uses_mineru(tmp_path: Path) -> None:
    pdf = _make_emptyish_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "scan.md"
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"providers": {"mineru": {"api_key": "tok", "api_base": "https://m.test"}}}),
        encoding="utf-8",
    )

    with (
        patch("pdf2md.fallback.load_mineru_config") as load_cfg,
        patch("pdf2md.fallback.parse_pdf", return_value="# OCR result\n") as parse,
    ):
        load_cfg.return_value = MagicMock()
        result = convert(pdf, out, ocr=True)

    assert result["parser"] == "mineru_vlm_ocr"
    assert out.read_text(encoding="utf-8") == "# OCR result\n"
    parse.assert_called_once()


def test_convert_no_ocr_keeps_local(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "rich.pdf",
                    "Plenty of local text here for sure to pass the quality threshold check")
    out = tmp_path / "local.md"

    with patch("pdf2md.fallback.parse_pdf") as parse:
        result = convert(pdf, out, ocr=False)

    assert result["parser"] == "local"
    parse.assert_not_called()
    assert out.exists()



def test_ocr_failed_falls_back_to_local(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "blank.pdf",
                    "Some text that can be extracted locally and is long enough to pass quality check")
    out = tmp_path / "blank.md"

    with patch(
        "pdf2md.fallback.load_mineru_config",
        side_effect=ValueError("config.json 中未配置 providers.mineru.api_key"),
    ):
        result = convert(pdf, out, ocr=True)

    assert result["parser"] == "local"
    assert result["fallback_reason"] == "ocr_failed_fallback_to_local"
    assert out.exists()


def test_both_ocr_and_local_fail(tmp_path: Path) -> None:
    """When OCR errors and local text is insufficient → Pdf2mdError."""
    pdf = _make_emptyish_pdf(tmp_path / "blank.pdf")
    out = tmp_path / "blank.md"

    with patch(
        "pdf2md.fallback.load_mineru_config",
        side_effect=ValueError("config.json 中未配置 providers.mineru.api_key"),
    ):
        with pytest.raises(Pdf2mdError, match="本地解析文本不足"):
            convert(pdf, out, ocr=True)
