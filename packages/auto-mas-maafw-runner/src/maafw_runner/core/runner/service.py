"""旧入口：``MaaFWRunnerService().build_plan(...)``，直接转调解析库的 ``build_maafw_run_plan``。

通用 MFW 专项还在顶层导入它（换成解析库之前得一直在，MFW 服务化实施方案 §11 L4），清理单删掉。
借还运行环境、worker 登记那一半已挪到 ``maafw_runner.host.runner_service``；本模块不导入
agent 环境与宿主。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from maafw_interface.interface.models import MaaFWInterface
from maafw_interface.runner.models import MaaFWRunPlan
from maafw_interface.runner.run_plan import build_maafw_run_plan


class MaaFWRunnerService:
    """maafw.runner.v1 service（只剩建计划）。"""

    def __init__(self, *, worker_registry: Any = None) -> None:
        # 旧签名照收；worker 登记已不在这里
        del worker_registry

    def build_plan(
        self,
        project_path: str | Path,
        interface: MaaFWInterface | dict[str, Any],
        *,
        controller_name: str | None = None,
        resource_name: str | None = None,
        selected_preset: str | None = None,
        task_snapshot: dict[str, Any] | None = None,
        task_ids: list[str] | None = None,
        task_options: dict[str, Any] | None = None,
        global_options: dict[str, Any] | None = None,
        script_hotkeys: dict[str, dict[str, str]] | None = None,
        secret_inputs: Any = None,
        no_default_fallback_inputs: Any = None,
        excluded_task_reasons: dict[str, str] | None = None,
        client_version: str = "",
    ) -> MaaFWRunPlan:
        # client_version：解析库不再自己读宿主 res/version.json，由调用方传宿主版本号
        # （写进 PI_CLIENT_VERSION），不传就是空串。
        return build_maafw_run_plan(
            project_path,
            self._coerce_interface(interface),
            controller_name=controller_name,
            resource_name=resource_name,
            selected_preset=selected_preset,
            task_snapshot=task_snapshot,
            task_ids=task_ids,
            task_options=task_options,
            global_options=global_options,
            script_hotkeys=script_hotkeys,
            secret_inputs=secret_inputs,
            no_default_fallback_inputs=no_default_fallback_inputs,
            excluded_task_reasons=excluded_task_reasons,
            client_version=client_version,
        )

    @staticmethod
    def _coerce_interface(interface: MaaFWInterface | dict[str, Any]) -> MaaFWInterface:
        if isinstance(interface, MaaFWInterface):
            return interface
        if hasattr(interface, "model_dump"):
            return MaaFWInterface.model_validate(
                interface.model_dump(mode="json", by_alias=True)
            )
        return MaaFWInterface.model_validate(interface)


__all__ = ["MaaFWRunnerService"]
