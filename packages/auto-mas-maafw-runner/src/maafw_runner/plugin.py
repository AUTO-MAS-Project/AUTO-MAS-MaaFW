"""MFW 运行积木的插件入口。

0.1.0 只登记服务名并认 ``version``；三个专项仍直接导入 ``maafw_runner.host.*`` 与
``maafw_runner.core.*``（拆分文档 §3.2 越界 S1），0.2 起按 §2.1 的目标 op 逐条改成服务。

规则 L：本模块顶层的导入链里不许出现别的插件包（agent 环境积木、项目更新积木、三个专项），
跨插件导入一律在函数体内。
"""

from __future__ import annotations

from typing import Any

from auto_mas_core import ExtensionPlugin

PACKAGE_NAME = "auto-mas-maafw-runner"
PACKAGE_VERSION = "0.1.0"
SERVICE_NAME = "maafw.runner.v1"


class Plugin(ExtensionPlugin):
    """跑 MFW 运行计划：worker、超时与打转保护、失败截图、日志打码。"""

    requires = ("maafw.agent_env.v1",)
    wants = ()
    provides_services = {SERVICE_NAME: "call"}

    async def call(self, op: str, /, **kwargs: Any) -> Any:
        """服务分发入口：0.1.0 只实现 ``version``；其余 op 见拆分文档 §2.1 的目标契约。"""

        if op == "version":
            return {"package": PACKAGE_NAME, "version": PACKAGE_VERSION}
        raise ValueError(f"未知操作: {op}")
