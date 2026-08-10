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
) -> None:
    """将 PDF 文件转换为 Markdown 文本并保存到指定路径。"""
    try:
        result = convert(input, output)
    except Pdf2mdError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e

    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
