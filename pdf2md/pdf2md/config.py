"""Load provider API config from the cli_tools repo config.json."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_MINERU_BASE_URL = "https://mineru.net"
DEFAULT_MODEL_VERSION = "vlm"
DEFAULT_POLL_INTERVAL_MS = 3000
DEFAULT_POLL_TIMEOUT_SECS = 300


class MinerUConfig:
    def __init__(
        self,
        api_key: str,
        api_base: str = DEFAULT_MINERU_BASE_URL,
        model_version: str = DEFAULT_MODEL_VERSION,
        poll_interval_ms: int = DEFAULT_POLL_INTERVAL_MS,
        poll_timeout_secs: int = DEFAULT_POLL_TIMEOUT_SECS,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model_version = model_version
        self.poll_interval_ms = poll_interval_ms
        self.poll_timeout_secs = poll_timeout_secs


def repo_root() -> Path:
    """cli_tools_for_content_agent/ when running from the source tree."""
    return Path(__file__).resolve().parents[2]


def config_path() -> Path:
    """Locate config.json by walking up from this file, then from CWD."""
    starts = [Path(__file__).resolve().parent, Path.cwd()]
    seen: set[Path] = set()
    for start in starts:
        for directory in [start, *start.parents]:
            if directory in seen:
                continue
            seen.add(directory)
            candidate = directory / "config.json"
            if candidate.is_file():
                return candidate
    return repo_root() / "config.json"


def load_raw_config(path: Path | None = None) -> dict:
    """Read config.json raw content.

    A missing file yields ``{}``; a read / JSON parse failure raises
    ValueError so the real cause is never silently masked as "not configured".
    """
    cfg_path = path or config_path()
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"读取 config.json 失败（{cfg_path}）: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json JSON 解析失败（{cfg_path}）: {e}") from e
    return data if isinstance(data, dict) else {}


def get_provider_config(provider_name: str, path: Path | None = None) -> dict[str, str]:
    """Read providers.<name>.{api_key, api_base} from config.json."""
    root = load_raw_config(path)
    providers = root.get("providers")
    if not isinstance(providers, dict):
        return {}
    entry = providers.get(provider_name)
    if entry is None:
        return {}
    if not isinstance(entry, dict):
        raise ValueError(
            f"config.json 中 providers.{provider_name} 配置必须是对象"
            f"（当前为 {type(entry).__name__}）"
        )
    result: dict[str, str] = {}
    api_key = entry.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        result["api_key"] = api_key.strip()
    api_base = entry.get("api_base")
    if isinstance(api_base, str) and api_base.strip():
        result["api_base"] = api_base.strip()
    return result


def load_mineru_config(path: Path | None = None) -> MinerUConfig:
    """Load MinerU settings from config.json. Raises ValueError if api_key missing."""
    cfg = get_provider_config("mineru", path)
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise ValueError(
            f"config.json 中未配置 providers.mineru.api_key（期望路径: {path or config_path()}）"
        )
    api_base = cfg.get("api_base") or DEFAULT_MINERU_BASE_URL
    return MinerUConfig(api_key=api_key, api_base=api_base)
