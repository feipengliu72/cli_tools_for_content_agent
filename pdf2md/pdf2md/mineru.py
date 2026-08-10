"""MinerU v4 API client: upload PDF, poll, extract full.md."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import httpx

from pdf2md.config import MinerUConfig


class MinerUError(Exception):
    """MinerU OCR / API failure."""


def parse_pdf(path: Path, config: MinerUConfig) -> str:
    """Upload PDF to MinerU, wait for parse, return Markdown text."""
    path = Path(path)
    file_name = path.name
    if not file_name:
        raise MinerUError("无法获取 PDF 文件名")

    timeout = httpx.Timeout(120.0, connect=30.0)
    with httpx.Client(timeout=timeout) as client:
        batch_id, upload_url = _request_upload_url(client, config, file_name)
        _upload_file(client, path, upload_url)
        zip_url = _poll_batch_result(client, config, batch_id, file_name)
        return _download_and_extract_md(client, zip_url)


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


def _upload_file(client: httpx.Client, path: Path, upload_url: str) -> None:
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise MinerUError(f"读取 PDF 文件失败: {e}") from e

    try:
        resp = client.put(upload_url, content=raw)
    except httpx.HTTPError as e:
        raise MinerUError(f"MinerU 上传文件失败: {e}") from e

    if resp.status_code >= 400:
        body = (resp.text or "")[:200]
        raise MinerUError(f"MinerU 上传文件失败: HTTP {resp.status_code} {body}")


def _poll_batch_result(
    client: httpx.Client,
    config: MinerUConfig,
    batch_id: str,
    file_name: str,
) -> str:
    url = f"{config.api_base}/api/v4/extract-results/batch/{batch_id}"
    deadline = time.monotonic() + max(config.poll_timeout_secs, 1)
    interval = max(config.poll_interval_ms, 100) / 1000.0

    while True:
        if time.monotonic() >= deadline:
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


def _download_and_extract_md(client: httpx.Client, zip_url: str) -> str:
    try:
        resp = client.get(zip_url)
    except httpx.HTTPError as e:
        raise MinerUError(f"下载 MinerU 结果失败: {e}") from e

    if resp.status_code >= 400:
        raise MinerUError(f"下载 MinerU 结果失败: HTTP {resp.status_code}")

    return extract_full_md_from_zip(resp.content)


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
    except zipfile.BadZipFile as e:
        raise MinerUError(f"解压 MinerU ZIP 失败: {e}") from e

    if best is None:
        raise MinerUError("MinerU ZIP 中未找到 full.md")
    return best[1]
