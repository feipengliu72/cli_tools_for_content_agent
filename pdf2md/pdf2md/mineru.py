"""MinerU v4 API client: upload PDF, poll, extract full.md."""

from __future__ import annotations

import io
import sys
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from pdf2md.config import MinerUConfig


class MinerUError(Exception):
    """MinerU OCR / API failure."""


def parse_pdf(
    path: Path,
    config: MinerUConfig,
    output_dir: Path | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    """Upload PDF to MinerU, wait for parse, return Markdown text.

    When ``output_dir`` is given, image files from the result ZIP are
    extracted to ``<output_dir>/images/``.

    ``progress_cb``, when set, receives one-line progress messages
    (upload node and waiting heartbeats).
    """
    path = Path(path)
    file_name = path.name
    if not file_name:
        raise MinerUError("无法获取 PDF 文件名")

    timeout = httpx.Timeout(120.0, connect=30.0)
    with httpx.Client(timeout=timeout) as client:
        batch_id, upload_url = _request_upload_url(client, config, file_name)
        _upload_file(client, path, upload_url, progress_cb=progress_cb)
        zip_url = _poll_batch_result(
            client, config, batch_id, file_name, progress_cb=progress_cb
        )
        return _download_and_extract_md(client, zip_url, output_dir)


def _ensure_api_ok(payload: dict, http_status: int, action: str) -> None:
    code = payload.get("code", -1)
    if code != 0:
        msg = payload.get("msg", "unknown")
        raise MinerUError(f"MinerU {action} 失败: {msg} (code={code})")
    if http_status >= 400:
        msg = payload.get("msg", "unknown")
        raise MinerUError(f"MinerU {action} 失败: HTTP {http_status} {msg}")


def _request_upload_url(
    client: httpx.Client, config: MinerUConfig, file_name: str
) -> tuple[str, str]:
    url = f"{config.api_base}/api/v4/file-urls/batch"
    body = {
        "files": [{"name": file_name, "is_ocr": True}],
        "model_version": config.model_version,
        "enable_table": True,
        "enable_formula": True,
        "language": "ch",
    }
    try:
        resp = client.post(
            url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    except httpx.HTTPError as e:
        raise MinerUError(f"MinerU 申请上传链接失败: {e}") from e

    try:
        payload = resp.json()
    except ValueError as e:
        raise MinerUError(f"MinerU 申请上传链接响应解析失败: {e}") from e

    _ensure_api_ok(payload if isinstance(payload, dict) else {}, resp.status_code, "申请上传链接")

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise MinerUError("MinerU 响应缺少 data 字段")

    batch_id = data.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        raise MinerUError("MinerU 响应缺少 batch_id")

    file_urls = data.get("file_urls")
    if not isinstance(file_urls, list) or not file_urls:
        raise MinerUError("MinerU 响应缺少 file_urls")
    upload_url = file_urls[0]
    if not isinstance(upload_url, str) or not upload_url:
        raise MinerUError("MinerU 响应缺少 file_urls")

    return batch_id, upload_url


def _upload_file(
    client: httpx.Client,
    path: Path,
    upload_url: str,
    progress_cb: Callable[[str], None] | None = None,
) -> None:
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise MinerUError(f"读取 PDF 文件失败: {e}") from e

    if progress_cb is not None:
        progress_cb(f"上传 PDF（{len(raw) / 1048576:.1f} MB）...")

    try:
        resp = client.put(upload_url, content=raw)
    except httpx.HTTPError as e:
        raise MinerUError(f"MinerU 上传文件失败: {e}") from e

    if resp.status_code >= 400:
        body = (resp.text or "")[:200]
        raise MinerUError(f"MinerU 上传文件失败: HTTP {resp.status_code} {body}")

    if progress_cb is not None:
        progress_cb("上传完成，等待 MinerU 解析")


def _poll_batch_result(
    client: httpx.Client,
    config: MinerUConfig,
    batch_id: str,
    file_name: str,
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    url = f"{config.api_base}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.monotonic() + max(config.poll_timeout_secs, 1)
    interval = max(config.poll_interval_ms, 100) / 1000.0
    start = time.monotonic()
    last_bucket = 0  # 已打印过的 10 秒时间桶

    while True:
        now = time.monotonic()
        if now >= deadline:
            raise MinerUError(f"MinerU 解析超时（{config.poll_timeout_secs} 秒）")

        try:
            resp = client.get(
                url,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as e:
            raise MinerUError(f"MinerU 查询任务失败: {e}") from e

        try:
            payload = resp.json()
        except ValueError as e:
            raise MinerUError(f"MinerU 查询任务响应解析失败: {e}") from e

        _ensure_api_ok(payload if isinstance(payload, dict) else {}, resp.status_code, "查询任务")

        data = payload.get("data") if isinstance(payload, dict) else None
        results = data.get("extract_result") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise MinerUError("MinerU 响应缺少 extract_result")

        item = None
        for r in results:
            if isinstance(r, dict) and r.get("file_name") == file_name:
                item = r
                break
        if item is None and results:
            first = results[0]
            item = first if isinstance(first, dict) else None
        if item is None:
            raise MinerUError("MinerU 响应中无任务结果")

        state = item.get("state") or "unknown"
        if progress_cb is not None and state not in ("done", "failed"):
            last_bucket = _report_waiting(progress_cb, now - start, last_bucket)
        if state == "done":
            zip_url = item.get("full_zip_url")
            if not isinstance(zip_url, str) or not zip_url:
                raise MinerUError("MinerU 任务完成但缺少 full_zip_url")
            return zip_url
        if state == "failed":
            err_msg = item.get("err_msg") or "未知错误"
            raise MinerUError(f"MinerU 解析失败: {err_msg}")
        if state in (
            "waiting-file",
            "pending",
            "running",
            "converting",
            "uploading",
        ):
            time.sleep(interval)
            continue
        raise MinerUError(f"MinerU 未知任务状态: {state}")


def _report_waiting(
    progress_cb: Callable[[str], None],
    elapsed: float,
    last_bucket: int,
) -> int:
    """Print a heartbeat line every ~10s while the task is not done.

    The poll response only reports waiting-file / pending / done — it
    never exposes ``running`` or per-page progress — so the queue wait
    is the only phase worth reporting. Tasks that finish within 10s
    stay silent apart from the upload node.
    """
    bucket = int(elapsed) // 10
    if bucket == last_bucket:
        return last_bucket
    progress_cb(f"等待解析（已用 {int(elapsed)}s）")
    return bucket


def _download_and_extract_md(
    client: httpx.Client, zip_url: str, output_dir: Path | None = None
) -> str:
    try:
        resp = client.get(zip_url)
    except httpx.HTTPError as e:
        raise MinerUError(f"下载 MinerU 结果失败: {e}") from e

    if resp.status_code >= 400:
        raise MinerUError(f"下载 MinerU 结果失败: HTTP {resp.status_code}")

    if output_dir is not None:
        _extract_images(resp.content, output_dir)
    return extract_full_md_from_zip(resp.content)


_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def _extract_images(data: bytes, output_dir: Path) -> None:
    """Extract images from the MinerU result ZIP into <output_dir>/images/.

    The ZIP nests each file's assets under one per-file folder; that top
    folder is dropped so the markdown's relative ``images/...`` links
    resolve. Failures are reported on stderr — image extraction is a side
    effect and must not sink an otherwise successful conversion.
    """
    img_dir = Path(output_dir)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if not name.lower().endswith(_IMAGE_SUFFIXES):
                    continue
                parts = Path(name).parts
                if any(part in ("..", "") for part in parts):
                    continue  # zip-slip guard
                if len(parts) > 1 and parts[0] != "images":
                    parts = parts[1:]
                target = img_dir.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
        print(f"提取 MinerU 图片失败: {e}", file=sys.stderr)


def extract_full_md_from_zip(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            best: tuple[int, str] | None = None
            for name in archive.namelist():
                if not name.endswith("full.md"):
                    continue
                content = archive.read(name).decode("utf-8", errors="replace")
                depth = name.count("/")
                if best is None or depth < best[0]:
                    best = (depth, content)
    except (zipfile.BadZipFile, RuntimeError) as e:
        raise MinerUError(f"解压 MinerU ZIP 失败: {e}") from e

    if best is None:
        raise MinerUError("MinerU ZIP 中未找到 full.md")
    if not best[1].strip():
        raise MinerUError("MinerU 解析结果 full.md 为空")
    return best[1]
