"""宿主侧跑计划用的小件：worker 进程登记、拼 job（搬自 ``core/runner/service.py``）。

借还运行环境改走 agent 环境的服务（``agent_env_client``），不在这里；建计划在解析库
（``maafw_interface.runner.run_plan.build_maafw_run_plan``），旧入口 ``core/runner/service.py`` 只剩
``build_plan`` 的薄壳（MFW 服务化实施方案 §5、§11 L4）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psutil
from maafw_interface.runner.models import (
    MaaFWDeviceConfig,
    MaaFWRunnerJobPayload,
    MaaFWRunPlan,
)

from .worker_registry import GLOBAL_MAAFW_WORKER_REGISTRY, MaaFWWorkerRegistry


class MaaFWRunnerService:
    """跑计划时的 worker 登记与 job 组装。"""

    def __init__(self, *, worker_registry: MaaFWWorkerRegistry | None = None) -> None:
        self._worker_registry = worker_registry or GLOBAL_MAAFW_WORKER_REGISTRY

    def register_worker(self, worker: Any) -> str | None:
        return self._worker_registry.register(worker)

    def unregister_worker(self, worker_id: str | None) -> None:
        self._worker_registry.unregister(worker_id)

    def create_job_payload(
        self,
        plan: MaaFWRunPlan | dict[str, Any],
        device_config: MaaFWDeviceConfig | dict[str, Any],
        *,
        failure_screenshot_dir: str | Path | None = None,
        failure_screenshot_prefix: str = "",
        task_start_not_before: float | None = None,
        task_start_gate_mode: str = "screen",
        run_deadline_at: float | None = None,
        task_time_limit_seconds: int = 0,
        task_time_limit_overrides: dict[str, int] | None = None,
        loop_guard: bool = False,
    ) -> MaaFWRunnerJobPayload:
        owner_pid = os.getpid()
        try:
            owner_create_time = psutil.Process(owner_pid).create_time()
        except psutil.Error:
            owner_create_time = None
        return MaaFWRunnerJobPayload(
            plan=plan
            if isinstance(plan, MaaFWRunPlan)
            else MaaFWRunPlan.model_validate(plan),
            deviceConfig=(
                device_config
                if isinstance(device_config, MaaFWDeviceConfig)
                else MaaFWDeviceConfig.model_validate(device_config)
            ),
            ownerPid=owner_pid,
            ownerCreateTime=owner_create_time,
            failureScreenshotDir=(
                str(failure_screenshot_dir)
                if failure_screenshot_dir is not None
                else None
            ),
            failureScreenshotPrefix=failure_screenshot_prefix,
            taskStartNotBefore=task_start_not_before,
            taskStartGateMode=task_start_gate_mode,
            runDeadlineAt=run_deadline_at,
            taskTimeLimitSeconds=task_time_limit_seconds,
            taskTimeLimitOverrides=task_time_limit_overrides,
            loopGuard=bool(loop_guard),
        )


__all__ = ["MaaFWRunnerService"]
