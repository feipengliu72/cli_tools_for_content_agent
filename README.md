# CLI Tools for Content Agent

命令行工具集，用于内容处理与分析。

## pdf2md

将 PDF 转为 Markdown。默认本地布局解析；文本不足或扫描件过多时自动 fallback 到 MinerU OCR（API 读自仓库根目录 `config.json`）。

### 用法

```bash
cd pdf2md
pip install -e .
pdf2md --input in.pdf --output out.md
pdf2md --input in.pdf --output out.md --no-ocr
pdf2md --input in.pdf --output out.md --force-ocr
```
