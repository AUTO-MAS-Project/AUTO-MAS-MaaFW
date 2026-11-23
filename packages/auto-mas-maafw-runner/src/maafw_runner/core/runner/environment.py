"""worker 进程里要先跑的那一步：把项目 runner venv 的 site-packages 排到 ``sys.path`` 最前。

借还运行环境、拼 worker 环境变量那一半在宿主侧（``maafw_runner.host.environment``，MFW 服务化
实施方案 §5）；本模块在 worker 里导入，不导入 agent 环境、宿主与 SDK。
"""

from __future__ import annotations

import sys
import sysconfig
from pathlib import Path


def prefer_active_venv_site_packages(
    site_packages: str | Path | None = None,
) -> Path | None:
    """Keep the project Runner packages ahead of shared plugin dependencies."""

    raw_path = site_packages or sysconfig.get_path("purelib")
    if not raw_path:
        return None

    active_site_packages = Path(raw_path).resolve()
    normalized_path = str(active_site_packages)
    sys.path[:] = [
        item for item in sys.path if _normalized_sys_path(item) != normalized_path
    ]
    sys.path.insert(0, normalized_path)
    return active_site_packages


def _normalized_sys_path(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError):
        return path


__all__ = ["prefer_active_venv_site_packages"]
