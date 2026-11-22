"""MFW 运行积木（``maafw_runner``）。

worker 子进程也会导入本包（``-m maafw_runner.core.runner.worker``），而 worker 所在的运行池
隔离 venv 里没有宿主与 SDK。所以这里顶层不导入 ``auto_mas_core`` 和插件类：插件加载器
用 ``getattr`` 取 ``PLUGIN`` / ``PLUGIN_API_VERSION`` 时，才经模块级 ``__getattr__``（PEP 562）
惰性导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .plugin import Plugin as PLUGIN  # noqa: F401

__all__ = ["PLUGIN", "PLUGIN_API_VERSION"]


def __getattr__(name: str) -> Any:
    if name == "PLUGIN":
        from .plugin import Plugin

        globals()["PLUGIN"] = Plugin
        return Plugin
    if name == "PLUGIN_API_VERSION":
        from auto_mas_core import PLUGIN_API_VERSION

        globals()["PLUGIN_API_VERSION"] = PLUGIN_API_VERSION
        return PLUGIN_API_VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
