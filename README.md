# CLI Tools for Content Agent

命令行工具集，用于内容处理与分析。

## pdf2md

将 PDF 转为 Markdown。默认使用 MinerU OCR 解析（API 读自 Python 运行环境 Lib 目录下的 `config.json`，如 `runtime/Lib/config.json`）；OCR 失败直接报错退出，可用 `--no-ocr` 仅本地解析。

### 用法

```bash
cd pdf2md
pip install -e .
pdf2md --input in.pdf --output out.md
pdf2md --input in.pdf --output out.md --no-ocr
```
