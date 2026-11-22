"""MFW Agent 环境插件实例：登记服务 ``maafw.agent_env.v1``。

0.1.0 只实现 ``version`` 一个操作。运行（``maafw_runner``）和项目更新
（``maafw_project_update``）照旧在函数体内直接导入 ``maafw_agent_env.core.*`` 与
``maafw_agent_env.host.*``；以后按拆分契约 §2.2 的目标操作逐条改成走本服务。

规则 L：本模块和它顶层的整条导入链里不出现别的插件包，只依赖 SDK。

SDK（``auto_mas_core``）一导入就要拉起宿主，所以插件类在第一次取 ``Plugin`` 时才建
（模块级 ``__getattr__``）：本模块在没有宿主的环境里也能导入，宿主里取到的是同一个类。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

#: 发行名与版本，``version`` 操作原样返回。
DISTRIBUTION = "auto-mas-maafw-agent-env"
VERSION = "0.1.0"

#: 本插件提供的服务名。
SERVICE = "maafw.agent_env.v1"

if TYPE_CHECKING:
    from auto_mas_core import ExtensionPlugin

    class Plugin(ExtensionPlugin):
        async def call(self, op: str, /, **kwargs: Any) -> Any: ...


__all__ = ["DISTRIBUTION", "SERVICE", "VERSION", "Plugin"]


def _build_plugin_class() -> type:
    """建插件类；只在宿主进程里调用（需要 SDK）。"""

    from auto_mas_core import ExtensionPlugin

    class Plugin(ExtensionPlugin):
        """运行池与项目 agent 环境的服务插件，不依赖别的插件。"""

        requires = ()
        wants = ()
        provides_services = {SERVICE: "call"}

        async def call(self, op: str, /, **kwargs: Any) -> Any:
            """服务分发入口：按 ``op`` 选择操作。

            0.1.0 只认 ``version``，返回 ``{"package": 发行名, "version": 版本}``；
            不认识的操作抛 ``ValueError``。
            """

            if op == "version":
                return {"package": DISTRIBUTION, "version": VERSION}
            raise ValueError(f"未知操作: {op}")

    Plugin.__module__ = __name__
    Plugin.__qualname__ = "Plugin"
    return Plugin


if not TYPE_CHECKING:

    def __getattr__(name: str) -> Any:
        """第一次取 ``Plugin`` 时建类并缓存在模块上。"""
        if name == "Plugin":
            value = _build_plugin_class()
            globals()[name] = value
            return value
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
