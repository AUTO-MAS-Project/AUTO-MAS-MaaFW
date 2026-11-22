"""MFW Agent 环境插件实例：登记服务 ``maafw.agent_env.v1.<操作>``（22 个）与旧的 ``maafw.agent_env.v1``。

每个操作一个服务名，映射到插件上同名的 async 方法（实现在 ``host/services.py``，契约在
``contract.py``）。旧的分发式服务 ``maafw.agent_env.v1``（``call(op, …)``，只认 ``version``）
在新旧并存期保留。运行（``maafw_runner``）和项目更新（``maafw_project_update``）现在仍在函数体内
直接导入 ``maafw_agent_env.core.*`` 与 ``maafw_agent_env.host.*``，那些函数原样保留，各自的服务化
单子再逐条改成走服务。

规则 L：本模块和它顶层的整条导入链里不出现别的插件包，只依赖 SDK。

SDK（``auto_mas_core``）一导入就要拉起宿主，所以插件类在第一次取 ``Plugin`` 时才建
（模块级 ``__getattr__``）：本模块在没有宿主的环境里也能导入，宿主里取到的是同一个类。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

#: 发行名与版本，``version`` 操作原样返回。
DISTRIBUTION = "auto-mas-maafw-agent-env"
VERSION = "0.2.0"

#: 本插件提供的服务族；旧的分发式服务也叫这个名字，新操作是 ``<族>.<操作>``。
SERVICE = "maafw.agent_env.v1"


def service_names() -> dict[str, str]:
    """``provides_services``：旧分发服务 + 22 个操作（服务名 → 插件上的方法名）。"""

    from .contract import OPERATIONS

    names = {SERVICE: "call"}
    names.update({f"{SERVICE}.{op}": op for op in OPERATIONS})
    return names


if TYPE_CHECKING:
    from auto_mas_core import ExtensionPlugin

    from .host.services import AgentEnvServices

    class Plugin(AgentEnvServices, ExtensionPlugin):
        async def call(self, op: str, /, **kwargs: Any) -> Any: ...


__all__ = ["DISTRIBUTION", "SERVICE", "VERSION", "Plugin", "service_names"]


def _build_plugin_class() -> type:
    """建插件类；只在宿主进程里调用（需要 SDK）。"""

    from auto_mas_core import ExtensionPlugin

    from .host.services import AgentEnvServices

    class Plugin(AgentEnvServices, ExtensionPlugin):
        """运行池与项目 agent 环境的服务插件，不依赖别的插件。"""

        requires = ()
        wants = ()
        provides_services = service_names()

        async def teardown_blockers(self) -> list[str]:
            """有没结束的环境准备 / 预检 / 回收、或交出去还没还的租约时，拒绝停用与重载。"""

            return self.service_blockers()

        async def on_disable(self) -> None:
            """停用：在途作业置停止并取消，没被取走的租约还掉，清空句柄表。"""

            await self.shutdown_services(teardown=False)

        async def on_teardown(self) -> None:
            """退出：在途作业置停止，最多等 2 秒，没被取走的租约还掉，清空句柄表。"""

            await self.shutdown_services(teardown=True)

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
