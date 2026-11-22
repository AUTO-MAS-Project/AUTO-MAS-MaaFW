#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""MFW 项目更新服务插件入口。

``PLUGIN``、``PLUGIN_API_VERSION`` 由模块级 ``__getattr__`` 惰性给出：专项在函数体内导入
``maafw_project_update.glue.*`` / ``host.*`` 时不连带导入插件类与 SDK（规则 L，见拆分契约 §2.0）。
加载器按 ``getattr`` 取这两个名字，PEP 562 的 ``__getattr__`` 能接住。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .plugin import Plugin as PLUGIN  # noqa: F401

__all__ = ["PLUGIN", "PLUGIN_API_VERSION"]


def __getattr__(name: str) -> Any:
    if name == "PLUGIN":
        from .plugin import Plugin

        return Plugin
    if name == "PLUGIN_API_VERSION":
        from auto_mas_core import PLUGIN_API_VERSION

        return PLUGIN_API_VERSION
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
