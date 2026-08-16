"""Tests for pdf2md CLI and core."""

from __future__ import annotations

import io
import json
import sysconfig
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest
from typer.testing import CliRunner

from pdf2md.cli import app
from pdf2md.config import MinerUConfig, config_path, load_mineru_config
from pdf2md.core import Pdf2mdError, convert, extract_text
from pdf2md.mineru import (
    MinerUError,
    _poll_batch_result,
    _upload_file,
    extract_full_md_from_zip,
)
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


def test_config_path_is_fixed_runtime_lib() -> None:
    """config.json must resolve to the running environment's Lib dir,
    independent of CWD and source checkout."""
    assert config_path() == Path(sysconfig.get_path("stdlib")) / "config.json"


def test_load_mineru_config_missing_key(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {"mineru": {"api_key": ""}}}), encoding="utf-8")
    with pytest.raises(ValueError, match="api_key"):
        load_mineru_config(cfg)


def test_load_mineru_config_malformed_json(tmp_path: Path) -> None:
    """A corrupt config.json must surface the JSON parse error, not
    masquerade as a missing api_key."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON 解析失败"):
        load_mineru_config(cfg)


def test_load_mineru_config_non_object_entry(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"providers": {"mineru": "tok-123"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="必须是对象"):
        load_mineru_config(cfg)


def test_extract_full_md_from_zip() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("nested/dir/full.md", "# deep")
        zf.writestr("full.md", "# root")
    md = extract_full_md_from_zip(buf.getvalue())
    assert md == "# root"


def test_extract_full_md_from_zip_empty() -> None:
    """An empty full.md is an OCR failure signature and must raise."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("full.md", "  \n")
    with pytest.raises(MinerUError, match="为空"):
        extract_full_md_from_zip(buf.getvalue())


def test_convert_ocr_uses_mineru(tmp_path: Path) -> None:
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



def test_ocr_failed_raises_error_no_fallback(tmp_path: Path) -> None:
    """OCR failure now raises Pdf2mdError directly (local fallback disabled).

    Even when the PDF has extractable local text, the error must surface
    and no output file may be written.
    """
    pdf = _make_pdf(tmp_path / "scan.pdf",
                    "Some text that can be extracted locally and is long enough to pass quality check")
    out = tmp_path / "scan.md"

    with patch(
        "pdf2md.fallback.load_mineru_config",
        side_effect=ValueError("config.json 中未配置 providers.mineru.api_key"),
    ):
        with pytest.raises(Pdf2mdError, match="MinerU"):
            convert(pdf, out, ocr=True)

    assert not out.exists()


def test_ocr_unexpected_exception_wrapped(tmp_path: Path) -> None:
    """Non-MinerUError exceptions from the OCR pipeline must surface as
    Pdf2mdError with the original type named, not as a raw traceback."""
    pdf = _make_emptyish_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "scan.md"

    with (
        patch("pdf2md.fallback.load_mineru_config") as load_cfg,
        patch("pdf2md.fallback.parse_pdf", side_effect=RuntimeError("boom")) as parse,
    ):
        load_cfg.return_value = MagicMock()
        with pytest.raises(Pdf2mdError, match="RuntimeError"):
            convert(pdf, out, ocr=True)

    parse.assert_called_once()
    assert not out.exists()


def _fake_resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.status_code = 200
    resp.text = ""
    return resp


def _poll_payload(state: str, **extra: object) -> dict:
    item: dict = {"file_name": "a.pdf", "state": state}
    item.update(extra)
    return {"code": 0, "data": {"extract_result": [item]}}


def test_upload_progress_lines(tmp_path: Path) -> None:
    """Upload step reports file size before PUT and completion after."""
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x" * 100)
    client = MagicMock()
    client.put.return_value = _fake_resp({})
    lines: list[str] = []

    _upload_file(client, pdf, "https://up.test", progress_cb=lines.append)

    assert lines[0].startswith("上传 PDF（")
    assert lines[-1] == "上传完成，等待 MinerU 解析"


def test_poll_waiting_heartbeat_every_10s() -> None:
    """Queue waits print a heartbeat roughly every 10 seconds; tasks
    finishing quickly stay silent apart from the upload node."""
    client = MagicMock()
    client.get.side_effect = [
        _fake_resp(_poll_payload("waiting-file")),
        _fake_resp(_poll_payload("waiting-file")),
        _fake_resp(_poll_payload("waiting-file")),
        _fake_resp(_poll_payload("waiting-file")),
        _fake_resp(_poll_payload("done", full_zip_url="https://z.test")),
    ]
    lines: list[str] = []
    clock = [
        1000.0,  # deadline
        1000.0,  # start
        1001.0,  # poll 1 (silent)
        1004.0,  # poll 2 (silent)
        1011.0,  # poll 3 (first heartbeat)
        1021.0,  # poll 4 (second heartbeat)
        1031.0,  # poll 5 (done, no heartbeat)
    ]

    with (
        patch("pdf2md.mineru.time.sleep"),
        patch("pdf2md.mineru.time.monotonic", side_effect=clock),
    ):
        zip_url = _poll_batch_result(
            client,
            MinerUConfig("tok"),
            "b1",
            "a.pdf",
            progress_cb=lines.append,
        )

    assert zip_url == "https://z.test"
    assert lines == ["等待解析（已用 11s）", "等待解析（已用 21s）"]


def test_cli_ocr_progress_goes_to_stderr(tmp_path: Path) -> None:
    """Progress lines land on stderr; stdout stays a pure JSON result."""
    pdf = _make_emptyish_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "scan.md"

    def fake_parse(path, config, output_dir=None, progress_cb=None):
        if progress_cb is not None:
            progress_cb("上传 PDF（0.0 MB）...")
        return "# OCR result\n"

    with (
        patch("pdf2md.fallback.load_mineru_config") as load_cfg,
        patch("pdf2md.fallback.parse_pdf", side_effect=fake_parse),
    ):
        load_cfg.return_value = MagicMock()
        result = runner.invoke(app, ["--input", str(pdf), "--output", str(out)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "上传 PDF" in result.stderr
    assert "上传 PDF" not in result.stdout
