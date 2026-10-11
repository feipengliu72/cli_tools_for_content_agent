import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from orange_attendance_tools.client import fetch_day, fetch_grid, fetch_stat, load_cookies, require_team_id
from orange_attendance_tools.transforms import transform_day, transform_grid, transform_stat
from orange_attendance_tools.yaml_writer import write_yaml

app = typer.Typer(add_completion=False, no_args_is_help=True, help="橙子办公考勤 YAML 命令行工具。")


def _validate_date(value: str) -> str:
    date.fromisoformat(value)
    return value


def _validate_month(value: str) -> str:
    year, month = value.split("-", 1)
    if len(year) != 4 or len(month) != 2:
        raise typer.BadParameter("月份格式必须为 YYYY-MM")
    date(int(year), int(month), 1)
    return value


def _emit_result(tool: str, output: Path, record_count: int, query: dict[str, str]) -> None:
    typer.echo(
        json.dumps(
            {
                "ok": True,
                "tool": tool,
                "output": str(output.resolve()),
                "record_count": record_count,
                "query": query,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def day(
    date_value: Annotated[str, typer.Option("--date", help="查询日期，格式 YYYY-MM-DD")],
    output: Annotated[Path, typer.Option("--output", help="YAML 输出文件路径", dir_okay=False)],
    team_id: Annotated[str | None, typer.Option("--team-id", help="团队编号")] = None,
) -> None:
    """查询指定日期的全员考勤状态并写入 YAML 文件。"""
    date_value = _validate_date(date_value)
    resolved_team_id = require_team_id(team_id)
    cookies = load_cookies()
    response = fetch_day(date_value, resolved_team_id, cookies)
    grid_records = fetch_grid(date_value[:7], resolved_team_id, "", cookies)
    payload = transform_day(response, grid_records, date_value)
    write_yaml(payload, output)
    _emit_result(
        "orange-attendance day",
        output,
        len(payload),
        {"type": "day", "team_id": resolved_team_id, "date": date_value},
    )


@app.command()
def grid(
    month: Annotated[str, typer.Option("--month", help="查询月份，格式 YYYY-MM")],
    output: Annotated[Path, typer.Option("--output", help="YAML 输出文件路径", dir_okay=False)],
    team_id: Annotated[str | None, typer.Option("--team-id", help="团队编号")] = None,
    department_id: Annotated[str, typer.Option("--department-id", help="部门编号")] = "",
) -> None:
    """查询整月全员每日考勤网格并写入 YAML 文件。"""
    month = _validate_month(month)
    resolved_team_id = require_team_id(team_id)
    response = fetch_grid(month, resolved_team_id, department_id, load_cookies())
    payload = transform_grid(response, resolved_team_id, month, department_id)
    write_yaml(payload, output)
    _emit_result("orange-attendance grid", output, payload["record_count"], payload["query"])


@app.command()
def stat(
    month: Annotated[str, typer.Option("--month", help="查询月份，格式 YYYY-MM")],
    output: Annotated[Path, typer.Option("--output", help="YAML 输出文件路径", dir_okay=False)],
    team_id: Annotated[str | None, typer.Option("--team-id", help="团队编号")] = None,
    department_id: Annotated[str, typer.Option("--department-id", help="部门编号")] = "",
) -> None:
    """查询整月全员考勤统计并写入 YAML 文件。"""
    month = _validate_month(month)
    resolved_team_id = require_team_id(team_id)
    response = fetch_stat(month, resolved_team_id, department_id, load_cookies())
    payload = transform_stat(response, resolved_team_id, month, department_id)
    write_yaml(payload, output)
    _emit_result("orange-attendance stat", output, payload["record_count"], payload["query"])
