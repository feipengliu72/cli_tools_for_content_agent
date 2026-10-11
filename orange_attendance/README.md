# 橙子办公考勤 CLI 工具

## 安装

```powershell
Set-Location 'D:\work\销售系统\orange-office'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install '.[dev]'
```

## 配置会话

在当前 PowerShell 窗口设置客户授权账号的完整 Cookie 与团队编号：

```powershell
$env:ORANGE_COOKIE = '完整 Cookie'
$env:ORANGE_TEAM_ID = '682452'
```

Cookie 会话失效后，命令会终止并显示 `sessionTimeout`。重新登录橙子办公并更新 `ORANGE_COOKIE` 后即可继续调用。

## 命令

```powershell
# 指定日期的全员考勤状态
.\.venv\Scripts\orange-attendance.exe day `
  --date 2026-10-10 `
  --output .\output\attendance-day-2026-10-10.yaml

# 指定月份的全员每日考勤网格
.\.venv\Scripts\orange-attendance.exe grid `
  --month 2026-10 `
  --output .\output\attendance-grid-2026-10.yaml

# 指定月份的全员考勤统计
.\.venv\Scripts\orange-attendance.exe stat `
  --month 2026-10 `
  --output .\output\attendance-stat-2026-10.yaml
```

`grid` 与 `stat` 支持 `--department-id`；三个命令均支持 `--team-id` 覆盖环境变量中的团队编号。

命令成功后标准输出返回 JSON，包含输出文件绝对路径、查询参数和记录数量。数据写入 UTF-8 YAML 文件；`output/` 已加入忽略规则。

YAML 文件仅包含考勤需要的人员编号、姓名、部门、打卡时间、考勤状态、考勤汇总及月度统计。Cookie、定位、手机号、头像、图片地址和设备标识不会写入文件。
