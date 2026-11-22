"""MFW Agent 环境插件：运行池与项目 agent 的 Python 环境。

worker 子进程也会导入 ``maafw_agent_env.core``，那里没有宿主和 SDK，所以本模块顶层
不导入 ``auto_mas_core`` 和插件类。插件加载器用 ``getattr`` 取 ``PLUGIN`` /
``PLUGIN_API_VERSION``，由下面的模块级 ``__getattr__``（PEP 562）惰性给出。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .plugin import Plugin as PLUGIN  # noqa: F401

__all__ = ["PLUGIN", "PLUGIN_API_VERSION"]


if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        """惰性给出插件入口类与插件协议版本，取到后缓存在模块上。"""
        if name == "PLUGIN":
            from .plugin import Plugin as value
        elif name == "PLUGIN_API_VERSION":
            from auto_mas_core import PLUGIN_API_VERSION as value
        else:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        globals()[name] = value
        return value
