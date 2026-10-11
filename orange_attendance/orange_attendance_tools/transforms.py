import calendar
from datetime import datetime, timezone
from typing import Any


def retrieved_at() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _text(value: Any) -> str | None:
    if value in (None, "", "0001-01-01 00:00:00"):
        return None
    return str(value)


def _identifier(value: Any) -> str | None:
    if value in (None, "", 0, "0"):
        return None
    return str(value)


def _punch(record: dict[str, Any], sequence: int, direction: str) -> dict[str, Any]:
    suffix = "" if sequence == 1 else str(sequence)
    prefix = "in" if direction == "in" else "out"
    return {
        "sequence": sequence,
        "direction": direction,
        "time": _text(record.get(f"temp{prefix.capitalize()}Time{suffix}")),
        "status": _text(record.get(f"{prefix}Status{suffix}")),
        "diff_minutes": record.get(f"{prefix}Diff{suffix}", 0),
        "supplemented": bool(record.get(f"{prefix}BukaId{suffix}", 0)),
    }


def transform_day(response: dict[str, Any], team_id: str, date: str) -> dict[str, Any]:
    summary = response.get("stat")
    records = response.get("list")
    if not isinstance(summary, dict) or not isinstance(records, list):
        raise ValueError("day 接口响应缺少 stat 或 list")

    employees = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("day 接口的人员记录格式无效")
        employee_id = _identifier(record.get("userId")) or _identifier(record.get("userId2"))
        if employee_id is None:
            raise ValueError("day 接口返回了缺少人员编号的记录")
        employees.append(
            {
                "employee_id": employee_id,
                "employee_name": _text(record.get("userName")),
                "department_id": _identifier(record.get("deptId")),
                "department_name": _text(record.get("deptName")),
                "record_date": _text(record.get("recDate")),
                "punches": [
                    _punch(record, 1, "in"),
                    _punch(record, 1, "out"),
                    _punch(record, 2, "in"),
                    _punch(record, 2, "out"),
                ],
            }
        )

    return {
        "source": "orange-office",
        "query": {"type": "day", "team_id": team_id, "date": date},
        "retrieved_at": retrieved_at(),
        "record_count": len(employees),
        "summary": {
            "late": summary.get("late", 0),
            "leave_early": summary.get("leaveEarly", 0),
            "leave": summary.get("vacate", 0),
            "outing": summary.get("outing", 0),
            "travelling": summary.get("travelling", 0),
            "overtime": summary.get("overtime", 0),
            "rest": summary.get("rest", 0),
            "in_lack": summary.get("inLack", 0),
            "out_lack": summary.get("outLack", 0),
            "in_buka": summary.get("inBuka", 0),
            "out_buka": summary.get("outBuka", 0),
        },
        "employees": employees,
    }


def transform_grid(records: list[dict[str, Any]], team_id: str, month: str, department_id: str) -> dict[str, Any]:
    year, month_number = map(int, month.split("-"))
    day_count = calendar.monthrange(year, month_number)[1]
    employees = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("grid 接口的人员记录格式无效")
        employee_id = _identifier(record.get("userId"))
        if employee_id is None:
            raise ValueError("grid 接口返回了缺少人员编号的记录")
        days = {}
        for day in range(1, day_count + 1):
            date = f"{month}-{day:02d}"
            days[date] = {
                "in": _text(record.get(f"{day}号上班")),
                "out": _text(record.get(f"{day}号下班")),
            }
        employees.append(
            {
                "employee_id": employee_id,
                "employee_name": _text(record.get("姓名")),
                "days": days,
            }
        )
    return {
        "source": "orange-office",
        "query": {
            "type": "grid",
            "team_id": team_id,
            "month": month,
            "department_id": department_id,
        },
        "retrieved_at": retrieved_at(),
        "record_count": len(employees),
        "employees": employees,
    }


def transform_stat(response: dict[str, Any], team_id: str, month: str, department_id: str) -> dict[str, Any]:
    records = response.get("list")
    if not isinstance(records, list):
        raise ValueError("stat 接口响应缺少 list")
    field_map = {
        "late_count": "lateCount",
        "late_minutes": "lateMinute",
        "leave_early_count": "leaveEarlyCount",
        "leave_early_minutes": "leaveEarlyMinute",
        "vacate": "vacate",
        "vacate_personal_leave": "vacatePersonalLeave",
        "vacate_sick_leave": "vacateSickLeave",
        "vacate_days_off": "vacateDaysOff",
        "vacate_annual_leave": "vacateAnnualLeave",
        "vacate_marital_leave": "vacateMaritalLeave",
        "vacate_maternity_leave": "vacateMaternityLeave",
        "vacate_paternity_leave": "vacatePaternityLeave",
        "vacate_parental_leave": "vacateParentalLeave",
        "home_leave": "homeLeave",
        "parental_care_leave": "parentalCareLeave",
        "vacate_other": "vacateOther",
        "outing": "outing",
        "outing_hours": "outingHour",
        "travelling": "travelling",
        "travelling_hours": "travellingHour",
        "overtime": "overtime",
        "overtime_hours": "overtimeHour",
        "in_lack_count": "inLackCount",
        "out_lack_count": "outLackCount",
        "lack_count": "lackCount",
        "supplement_count": "bukaCount",
        "attendance_days": "recDayCount",
        "attendance_hours": "recHourCount",
        "working_hours": "workingHourCount",
    }
    employees = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("stat 接口的人员记录格式无效")
        employee_id = _identifier(record.get("userId"))
        if employee_id is None:
            raise ValueError("stat 接口返回了缺少人员编号的记录")
        attendance = {key: record.get(value, 0) for key, value in field_map.items()}
        employees.append(
            {
                "employee_id": employee_id,
                "employee_name": _text(record.get("userName")),
                "department_id": _identifier(record.get("deptId")),
                "department_name": _text(record.get("deptName")),
                "attendance": attendance,
            }
        )
    return {
        "source": "orange-office",
        "query": {
            "type": "stat",
            "team_id": team_id,
            "month": month,
            "department_id": department_id,
        },
        "retrieved_at": retrieved_at(),
        "record_count": len(employees),
        "employees": employees,
    }
