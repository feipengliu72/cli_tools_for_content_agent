# 橙子办公考勤 CLI 工具

从橙子办公读取考勤数据并写入 UTF-8 YAML 文件。运行环境需要 Python 3.10 或更高版本，以及可访问橙子办公的有效账号会话。

## 安装

先获取本仓库，然后进入 `orange_attendance` 目录。以下命令以 Windows PowerShell 为例：

```powershell
git clone https://github.com/feipengliu72/cli_tools_for_content_agent.git
Set-Location .\cli_tools_for_content_agent\orange_attendance
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

在 macOS 或 Linux 中创建并启用虚拟环境：

```bash
cd cli_tools_for_content_agent/orange_attendance
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

如需运行测试，请将最后一条安装命令改为 `python -m pip install '.[dev]'`，然后执行 `python -m pytest`。

## 配置会话

在每次调用命令前，于当前终端设置完整 Cookie 和所属团队编号。Cookie 属于敏感凭据，请勿提交到仓库、聊天记录或共享文档。

```powershell
$env:ORANGE_COOKIE = '完整 Cookie'
$env:ORANGE_TEAM_ID = '团队编号'
```

Cookie 会话失效后，命令会终止并显示 `sessionTimeout`。重新登录橙子办公并更新 `ORANGE_COOKIE` 后即可继续调用。

## 命令

虚拟环境已启用时，可直接调用 `orange-attendance`：

```powershell
# 指定日期的全员考勤状态
orange-attendance day `
  --date 2026-10-10 `
  --output .\output\attendance-day-2026-10-10.yaml

# 指定月份的全员每日考勤网格
orange-attendance grid `
  --month 2026-10 `
  --output .\output\attendance-grid-2026-10.yaml

# 指定月份的全员考勤统计
orange-attendance stat `
  --month 2026-10 `
  --output .\output\attendance-stat-2026-10.yaml
```

未启用虚拟环境时，Windows 可使用 `./.venv/Scripts/orange-attendance.exe`；macOS 和 Linux 可使用 `./.venv/bin/orange-attendance`。

`grid` 与 `stat` 支持 `--department-id`。三个命令都支持 `--team-id`，该参数会覆盖 `ORANGE_TEAM_ID`。可执行 `orange-attendance --help` 查看完整参数。

命令成功后标准输出返回 JSON，包含输出文件绝对路径、查询参数和记录数量。数据写入 UTF-8 YAML 文件；`output/` 已加入忽略规则。`day` 的每位员工记录包含 `daily_status`：原始网格状态 `grid_in`、`grid_out`，以及 `is_leave`、`is_late`、`is_leave_early`、`is_missing_punch`、`is_rest`、`is_outing`、`is_travelling`、`is_overtime` 标记。

YAML 文件仅包含考勤需要的人员编号、姓名、部门、打卡时间、考勤状态、考勤汇总及月度统计。Cookie、定位、手机号、头像、图片地址和设备标识不会写入文件。
