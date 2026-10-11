# CLI Tools for Content Agent

命令行工具集，用于内容处理与分析。

## pdf2md

将 PDF 转为 Markdown。默认使用 MinerU OCR 解析（API 读自 Python 运行环境 Lib 目录下的 `config.json`，如 `runtime/Lib/config.json`）；OCR 失败直接报错退出，可用 `--no-ocr` 仅本地解析。OCR 进度（上传、排队等待心跳）打印到 stderr，stdout 仅输出 JSON 结果。

### 用法

```bash
cd pdf2md
pip install -e .
pdf2md --input in.pdf --output out.md
pdf2md --input in.pdf --output out.md --no-ocr
```

## orange_attendance

读取橙子办公考勤数据并输出 UTF-8 YAML 文件。需要 Python 3.10 或更高版本，以及可访问橙子办公的有效账号会话。

### 用法

```bash
cd orange_attendance
python -m venv .venv
# Windows PowerShell：.\.venv\Scripts\Activate.ps1
# macOS/Linux：source .venv/bin/activate
python -m pip install .
```

调用前请在当前终端设置完整 Cookie 与团队编号：

```powershell
$env:ORANGE_COOKIE = '完整 Cookie'
$env:ORANGE_TEAM_ID = '团队编号'
orange-attendance day --date 2026-10-10 --output .\output\attendance-day-2026-10-10.yaml
```

Cookie 属于敏感凭据，请勿提交到仓库。完整的安装方式、macOS/Linux 调用路径和 `grid`、`stat` 命令参数见 [orange_attendance/README.md](orange_attendance/README.md)。

`day` 输出中的每位员工均包含 `daily_status`，其中提供请假、迟到、早退、缺卡、休息、外出、出差、加班标记，以及当天网格中的原始上下班状态。
