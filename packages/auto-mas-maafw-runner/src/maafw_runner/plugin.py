"""MFW 运行积木的插件入口。

0.1.0 只登记服务名并认 ``version``；三个专项仍直接导入 ``maafw_runner.host.*`` 与
``maafw_runner.core.*``（拆分文档 §3.2 越界 S1），0.2 起按 §2.1 的目标 op 逐条改成服务。

借还运行环境走 agent 环境的服务（``requires`` 里那 5 个，MFW 服务化实施方案 §3.2）：专项旧路径
直接建的 ``MaaFWPlanRun`` 用 ``on_enable`` 时绑在 ``host.agent_env_client`` 上的解析器。

规则 L：本模块顶层的导入链里不许出现别的插件包（agent 环境积木、项目更新积木、三个专项），
跨插件导入一律在函数体内。
"""

from __future__ import annotations

from typing import Any

from auto_mas_core import ExtensionPlugin

from .host.agent_env_client import AGENT_ENV_REQUIRES

PACKAGE_NAME = "auto-mas-maafw-runner"
PACKAGE_VERSION = "0.2.0"
SERVICE_NAME = "maafw.runner.v1"


class Plugin(ExtensionPlugin):
    """跑 MFW 运行计划：worker、超时与打转保护、失败截图、日志打码。"""

    requires = AGENT_ENV_REQUIRES
    wants = ()
    provides_services = {SERVICE_NAME: "call"}

    async def call(self, op: str, /, **kwargs: Any) -> Any:
        """服务分发入口：0.1.0 只实现 ``version``；其余 op 见拆分文档 §2.1 的目标契约。"""

        if op == "version":
            return {"package": PACKAGE_NAME, "version": PACKAGE_VERSION}
        raise ValueError(f"未知操作: {op}")

    async def on_enable(self) -> None:
        """绑上解析器给旧路径借还运行环境用。"""

        from .host import agent_env_client

        agent_env_client.bind(getattr(self, "services", None))

    async def on_disable(self) -> None:
        from .host import agent_env_client

        agent_env_client.unbind(getattr(self, "services", None))

    async def on_teardown(self) -> None:
        from .host import agent_env_client

        agent_env_client.unbind(getattr(self, "services", None))

    async def teardown_blockers(self) -> list[str]:
        """有计划还在跑（含借环境、起 worker 之前）时拒绝停用、重载、卸载。

        宿主在拆整棵依赖树之前调；托管锁只挡住了经专项派发的运行，这里再兜一层，免得在途的 worker
        和运行环境被拆到一半。
        """

        from .host.plan_run import active_plan_runs

        count = active_plan_runs()
        if count:
            return [f"MFW 运行积木还有 {count} 个运行没有结束，请先停止任务再操作"]
        return []
