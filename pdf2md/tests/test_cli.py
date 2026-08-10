"""Tests for pdf2md CLI and core."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from typer.testing import CliRunner

from pdf2md.cli import app
from pdf2md.core import Pdf2mdError, convert, extract_text

runner = CliRunner()


def _make_pdf(path: Path, text: str = "Hello PDF") -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()
    return path


def test_extract_text_rejects_non_pdf(tmp_path: Path) -> None:
    fake = tmp_path / "not.pdf"
    fake.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(Pdf2mdError, match="不是有效的 PDF"):
        extract_text(fake)


def test_convert_writes_file_and_json_fields(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "sample.pdf", "Page one")
    out = tmp_path / "out" / "sample.md"

    result = convert(pdf, out)

    assert result["ok"] is True
    assert result["input"] == str(pdf)
    assert result["output"] == str(out)
    assert result["chars"] > 0
    assert out.exists()
    assert "Page one" in out.read_text(encoding="utf-8")


def test_cli_success_prints_json(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "cli.pdf", "CLI text")
    out = tmp_path / "cli.md"

    result = runner.invoke(
        app,
        ["--input", str(pdf), "--output", str(out)],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["output"] == str(out)
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
        ["--input", str(fake), "--output", str(out)],
    )

    assert result.exit_code == 1
    assert "不是有效的 PDF" in result.stderr
    assert not out.exists()
