import hashlib
import json
import os

import requests

BASE_URL = "https://orange-office.cn"
SIGN_SALT = "68756c61"
ERROR_STATES = {"sessionTimeout", "noTeam", "noPermit", "noMember", "error"}


class AttendanceApiError(RuntimeError):
    pass


def compact_json(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def compute_sign(body: str) -> str:
    return hashlib.md5((SIGN_SALT + body).encode("utf-8")).hexdigest()


def load_cookies() -> dict[str, str]:
    raw = os.environ.get("ORANGE_COOKIE", "").strip()
    if not raw:
        raise AttendanceApiError("缺少环境变量 ORANGE_COOKIE")
    if "=" not in raw:
        raw = f"ASP.NET_SessionId={raw}"

    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    if not cookies:
        raise AttendanceApiError("ORANGE_COOKIE 中没有可用的 Cookie 字段")
    return cookies


def require_team_id(value: str | None) -> str:
    team_id = value or os.environ.get("ORANGE_TEAM_ID", "").strip()
    if not team_id:
        raise AttendanceApiError("缺少团队编号，请通过 --team-id 或 ORANGE_TEAM_ID 提供")
    return str(team_id)


def call(path: str, payload: dict[str, object], cookies: dict[str, str]) -> object:
    body = compact_json(payload)
    response = requests.post(
        BASE_URL + path,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "sign": compute_sign(body),
            "client": "pcWeb",
        },
        cookies=cookies,
        timeout=30,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    result = response.json()
    state = result.get("state")
    if state in ERROR_STATES:
        raise AttendanceApiError(f"{path} 返回状态 {state}: {result.get('msg')}")
    return result.get("obj")


def fetch_day(date: str, team_id: str, cookies: dict[str, str]) -> dict[str, object]:
    result = call("/attend/rec/getAttendByDate", {"teamId": team_id, "date": date}, cookies)
    if not isinstance(result, dict):
        raise AttendanceApiError("day 接口返回了无效的数据结构")
    return result


def fetch_grid(
    month: str,
    team_id: str,
    department_id: str,
    cookies: dict[str, str],
) -> list[dict[str, object]]:
    result = call(
        "/attend/rec/getDateList",
        {"teamId": team_id, "page": 1, "row": 10000, "ym": month, "deptId": department_id},
        cookies,
    )
    if not isinstance(result, list):
        raise AttendanceApiError("grid 接口返回了无效的数据结构")
    return result


def fetch_stat(
    month: str,
    team_id: str,
    department_id: str,
    cookies: dict[str, str],
) -> dict[str, object]:
    result = call(
        "/attend/rec/getStatListNew",
        {"teamId": team_id, "ym": month, "deptId": department_id},
        cookies,
    )
    if not isinstance(result, dict):
        raise AttendanceApiError("stat 接口返回了无效的数据结构")
    return result
