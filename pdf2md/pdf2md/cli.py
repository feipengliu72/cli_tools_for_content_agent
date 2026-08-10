"""Typer CLI for pdf2md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from pdf2md.core import Pdf2mdError, convert

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="将 PDF 文件转换为 Markdown 文本并保存到指定路径。",
)


@app.command()
def main(
    input: Annotated[
        Path,
        typer.Option("--input", help="PDF 文件路径", exists=False, dir_okay=False),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="输出 Markdown 文件路径", dir_okay=False),
    ],
    no_ocr: Annotated[
        bool,
        typer.Option("--no-ocr", help="禁用 MinerU OCR fallback，仅本地解析"),
    ] = False,
    force_ocr: Annotated[
        bool,
        typer.Option("--force-ocr", help="跳过本地判定，强制使用 MinerU OCR"),
    ] = False,
) -> None:
    """将 PDF 文件转换为 Markdown 文本并保存到指定路径。

    默认在本地文本不足或扫描件占比过高时自动 fallback 到 MinerU OCR
    （API 从仓库根目录 config.json 的 providers.mineru 读取）。
    """
    if no_ocr and force_ocr:
        typer.echo("错误: --no-ocr 与 --force-ocr 不能同时使用", err=True)
        raise typer.Exit(code=1)

    try:
        result = convert(
            input,
            output,
            ocr=not no_ocr,
            force_ocr=force_ocr,
        )
    except Pdf2mdError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
