from pathlib import Path
from typing import Any

import yaml


class QuotedString(str):
    pass


def _represent_quoted_string(dumper: yaml.SafeDumper, value: QuotedString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')


yaml.SafeDumper.add_representer(QuotedString, _represent_quoted_string)


def _quote_strings(value: Any) -> Any:
    if isinstance(value, str):
        return QuotedString(value)
    if isinstance(value, list):
        return [_quote_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: _quote_strings(item) for key, item in value.items()}
    return value


def write_yaml(payload: dict[str, Any], output: Path) -> None:
    if output.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("--output 必须使用 .yaml 或 .yml 扩展名")
    output.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        _quote_strings(payload),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=120,
    )
    output.write_text(text, encoding="utf-8")
