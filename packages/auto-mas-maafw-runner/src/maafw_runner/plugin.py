"""MFW 运行积木的插件入口：登记服务 ``maafw.runner.v1.<操作>``（29 个）与旧的 ``maafw.runner.v1``。

每个操作一个服务名，映射到插件上同名的方法（实现在 ``host/services.py``，契约在 ``contract.py``）。
旧的分发式服务 ``maafw.runner.v1``（``call(op, …)``，只认 ``version``）在新旧并存期保留。三个专项
现在仍直接导入 ``maafw_runner.host.*`` 与 ``maafw_runner.core.*``，那些类与函数原样保留，各自的服务化
单子再逐条改成走服务。

借还运行环境走 agent 环境的服务（``requires`` 里那 5 个，MFW 服务化实施方案 §3.2）：服务操作经本实例的
``self.services`` 调；专项旧路径直接建的 ``MaaFWPlanRun`` 用 ``on_enable`` 时绑在
``host.agent_env_client`` 上的解析器。

规则 L：本模块顶层的导入链里不许出现别的插件包（agent 环境积木、项目更新积木、三个专项），
跨插件导入一律在函数体内。
"""

from __future__ import annotations

from typing import Any

from auto_mas_core import ExtensionPlugin

from .contract import OPERATIONS
from .host.agent_env_client import AGENT_ENV_REQUIRES
from .host.services import RunnerServices

PACKAGE_NAME = "auto-mas-maafw-runner"
PACKAGE_VERSION = "0.2.0"
SERVICE_NAME = "maafw.runner.v1"


def service_names() -> dict[str, str]:
    """``provides_services``：旧分发服务 + 29 个操作（服务名 → 插件上的方法名）。"""

    names = {SERVICE_NAME: "call"}
    names.update({f"{SERVICE_NAME}.{op}": op for op in OPERATIONS})
    return names


class Plugin(RunnerServices, ExtensionPlugin):
    """跑 MFW 运行计划：worker、超时与打转保护、失败截图、日志打码。"""

    requires = AGENT_ENV_REQUIRES
    wants = ()
    provides_services = service_names()

    async def call(self, op: str, /, **kwargs: Any) -> Any:
        """服务分发入口：0.1.0 只实现 ``version``；其余 op 见拆分文档 §2.1 的目标契约。"""

        if op == "version":
            return {"package": PACKAGE_NAME, "version": PACKAGE_VERSION}
        raise ValueError(f"未知操作: {op}")

    async def on_enable(self) -> None:
        """绑上解析器给旧路径用；会在工作线程里被调的那几个模块先在事件循环上导入好。"""

        from .host import agent_env_client
        from .host import desktop_game as _desktop_game  # noqa: F401  desktop_check 在线程里用它

        agent_env_client.bind(getattr(self, "services", None))

    async def teardown_blockers(self) -> list[str]:
        """有在途作业的账号、或专项旧路径上还有计划在跑（含借环境、起 worker 之前）时拒绝停用、
        重载、卸载。

        宿主在拆整棵依赖树之前调；托管锁只挡住了经专项派发的运行，这里再兜一层，免得在途的 worker
        和运行环境被拆到一半。
        """

        return self.service_blockers()

    async def on_disable(self) -> None:
        """停用：在途作业置停止并取消，清空句柄表与账号，解绑旧路径用的解析器。"""

        from .host import agent_env_client

        await self.shutdown_services(teardown=False)
        agent_env_client.unbind(getattr(self, "services", None))

    async def on_teardown(self) -> None:
        """退出：在途作业置停止，最多等 2 秒，还挂着的 Unity 分辨率只恢复注册表，清空，解绑。"""

        from .host import agent_env_client

        await self.shutdown_services(teardown=True)
        agent_env_client.unbind(getattr(self, "services", None))
