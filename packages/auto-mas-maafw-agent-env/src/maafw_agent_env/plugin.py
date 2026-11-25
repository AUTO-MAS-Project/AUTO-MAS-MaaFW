"""MFW Agent 环境插件实例：登记服务 ``maafw.agent_env.v1.<操作>``（22 个）。

每个操作一个服务名，映射到插件上同名的 async 方法（实现在 ``host/services.py``，契约在
``contract.py``）。0.2 的分发式服务 ``maafw.agent_env.v1``（``call(op, …)``）已删（MFW 服务化实施方案
§2.1），版本走 ``maafw.agent_env.v1.version``。运行（``maafw_runner``）和项目更新
（``maafw_project_update``）的宿主侧只经这些服务调本包；只有运行的 worker 子进程经门面
``maafw_agent_env.core.worker_api`` 导入。

规则 L：本模块和它顶层的整条导入链里不出现别的插件包，只依赖 SDK。

SDK（``auto_mas_core``）一导入就要拉起宿主，所以插件类在第一次取 ``Plugin`` 时才建
（模块级 ``__getattr__``）：本模块在没有宿主的环境里也能导入，宿主里取到的是同一个类。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

#: 发行名与版本，``version`` 操作原样返回。
DISTRIBUTION = "auto-mas-maafw-agent-env"
VERSION = "0.3.0"

#: 本插件提供的服务族；每个操作的服务名是 ``<族>.<操作>``，族名本身不登记。
SERVICE = "maafw.agent_env.v1"


def service_names() -> dict[str, str]:
    """``provides_services``：22 个操作（服务名 → 插件上的方法名）。"""

    from .contract import OPERATIONS

    return {f"{SERVICE}.{op}": op for op in OPERATIONS}


if TYPE_CHECKING:
    from auto_mas_core import ExtensionPlugin

    from .host.services import AgentEnvServices

    class Plugin(AgentEnvServices, ExtensionPlugin): ...


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
