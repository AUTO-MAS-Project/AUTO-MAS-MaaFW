"""起 worker 用的运行环境（宿主侧）：把 agent 环境借来的结果拼成 worker 的环境变量与计划。

运行池（base venv、binding、native）归 agent 环境那一块管；借还走它的服务
（``maafw.agent_env.v1.borrow_*`` / ``borrow_return``，见 ``agent_env_client``），本模块不导入
``maafw_agent_env``。:func:`environment_from_borrow` 把借环境结果（普通数据）变成
:class:`MaaFWRunnerEnvironment`，用 :func:`build_runner_environment` 拼出 worker 的 ``PYTHONPATH`` 等；
:func:`worker_run_plan` 把借环境时算好的 agent 命令计划填进下发给 worker 的计划。

搬自 ``core/runner/environment.py``（MFW 服务化实施方案 §5）：worker 用的
``prefer_active_venv_site_packages`` 留在 ``core``。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maafw_native.subprocess_env import strip_host_python_environment

if TYPE_CHECKING:
    from maafw_interface.interface.agent_command import (
        MaaFWAgentCommandPlan,
    )
    from maafw_interface.runner.models import MaaFWRunPlan


@dataclass(frozen=True)
class MaaFWRunnerEnvironment:
    python_executable: Path
    venv_path: Path
    env: dict[str, str]
    packages: tuple[str, ...]
    maafw_version: str | None
    runtime_id: str | None = None
    maafw_requirement: str | None = None
    runtime_pool_root: Path | None = None
    runtime_pool_id: str | None = None
    lease_id: str | None = None
    #: 按版本存放的 binding 目录、其版本、以及池里的官方原生库目录（项目自带 DLL 时为 None）。
    binding_dir: Path | None = None
    binding_version: str | None = None
    native_dir: Path | None = None
    #: 借环境时 agent 环境按声明算出的 agent 命令计划（``MaaFWRuntimeLease.agent_plans``）。
    agent_plans: tuple[MaaFWAgentCommandPlan, ...] = ()


def _optional_path(value: Any) -> Path | None:
    return None if value in (None, "") else Path(str(value))


def environment_from_borrow(
    result: Mapping[str, Any], *, import_paths: Iterable[str | Path] = ()
) -> MaaFWRunnerEnvironment:
    """借环境结果（``borrow_poll`` 的终态，字段见 agent 环境 ``borrow_start``）拼成运行环境。

    ``import_paths`` 只决定 worker 的 ``PYTHONPATH``（binding 目录之后）；``worker_env`` 盖在最后。
    出错时由调用方把租约还掉。
    """

    from maafw_interface.interface.agent_command import MaaFWAgentCommandPlan

    venv_path = Path(str(result["venv_path"]))
    binding_dir = _optional_path(result.get("binding_dir"))
    worker_env = {
        str(key): str(value) for key, value in (result.get("worker_env") or {}).items()
    }
    env = build_runner_environment(
        venv_path,
        import_paths=import_paths,
        binding_dir=binding_dir,
        extra_env=worker_env,
    )
    return MaaFWRunnerEnvironment(
        python_executable=Path(str(result["python_executable"])),
        venv_path=venv_path,
        env=env,
        packages=tuple(str(item) for item in result.get("packages") or ()),
        maafw_version=result.get("maafw_version"),
        runtime_id=result.get("runtime_id"),
        maafw_requirement=result.get("maafw_requirement"),
        runtime_pool_root=_optional_path(result.get("runtime_pool_root")),
        runtime_pool_id=result.get("runtime_pool_id"),
        lease_id=result.get("lease_id"),
        binding_dir=binding_dir,
        binding_version=result.get("binding_version"),
        native_dir=_optional_path(result.get("native_dir")),
        agent_plans=tuple(
            MaaFWAgentCommandPlan.model_validate(item)
            for item in result.get("agent_plans") or ()
        ),
    )


def lease_fields(environment: MaaFWRunnerEnvironment) -> dict[str, Any]:
    """还环境（``borrow_return``）要的四个标识，只含 JSON 值。"""

    root = environment.runtime_pool_root
    return {
        "runtime_pool_root": None if root is None else str(root),
        "runtime_id": environment.runtime_id,
        "lease_id": environment.lease_id,
        "binding_version": environment.binding_version,
    }


def worker_run_plan(
    plan: MaaFWRunPlan,
    environment: MaaFWRunnerEnvironment,
    *,
    agent_plans: Sequence[MaaFWAgentCommandPlan] | None = None,
) -> MaaFWRunPlan:
    """下发给 worker 的计划：``plan`` 的深拷贝，填上 agent 命令计划，``PI_CLIENT_MAAFW_VERSION``
    换成这次实际加载的 binding 版本（借不出版本时保留建计划时的值）。

    ``agent_plans`` 缺省取 ``environment.agent_plans``；调用方要沿用早先算好的一份（同一账号
    这一轮的重试）时显式传。``plan`` 本身不改。
    """

    runner_plan = plan.model_copy(deep=True)
    source = environment.agent_plans if agent_plans is None else agent_plans
    runner_plan.agents = [agent.model_copy(deep=True) for agent in source]
    if environment.maafw_version:
        runner_plan.piEnv["PI_CLIENT_MAAFW_VERSION"] = (
            f"v{environment.maafw_version.lstrip('v')}"
        )
    return runner_plan


def build_runner_environment(
    venv_path: str | Path,
    *,
    import_paths: Iterable[str | Path] = (),
    binding_dir: str | Path | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """worker 子进程的环境变量。

    ``binding_dir`` 排在 ``PYTHONPATH`` 最前：base venv 里没有 ``maa``，``SOURCE_ROOT``
    与基解释器目录也没有，所以 ``import maa`` 落到它。``extra_env`` 是借运行环境时 agent
    环境给的键（``MaaFWRuntimeLease.worker_env``）：``MAAFW_BINARY_PATH`` 指到副本自带的
    ``maafw/`` 或池里的 native 目录（``maa/__init__.py`` 读它）——worker 与 binding 自检共用
    这几个键的拼法（``binding_environment_variables``），自检过了 worker 就一定能起；另有
    agent pip 约束文件的目录。最后盖上去。
    """

    # 宿主的 PYTHONPATH / PYTHONWARNINGS 等一律不进 worker：worker 能 import 什么只由
    # import_paths 决定（剔除名单与运行池 / agent 共用，见 host_environment 模块）。
    env = strip_host_python_environment()

    venv = Path(venv_path).resolve()
    scripts_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    resolved_import_paths = [
        str(Path(path).resolve()) for path in import_paths if Path(path).exists()
    ]
    if binding_dir is not None:
        resolved_import_paths.insert(0, str(Path(binding_dir).resolve()))

    env["VIRTUAL_ENV"] = str(venv)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # `python -m` 会把 cwd 插到 sys.path[0]，排在 PYTHONPATH 之前。受 Runtime 监督时
    # cwd 是 <app-root>，那里还躺着安装包自带的旧 app/ 包（只随整包安装更新），会把
    # PYTHONPATH 里的源码根整个盖掉，worker 于是跑上一个版本的引擎代码。这里禁掉 cwd
    # 前置，让 import_paths 说了算；worker 的 cwd 仍是 <app-root>，因为运行池、更新
    # 缓存等用户数据都按它解析。运行池的解释器约束是 3.12/3.13，该变量必然生效。
    env["PYTHONSAFEPATH"] = "1"
    env["PATH"] = f"{scripts_dir}{os.pathsep}{env.get('PATH', '')}"
    if resolved_import_paths:
        env["PYTHONPATH"] = os.pathsep.join(resolved_import_paths)
    else:
        env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    return env


__all__ = [
    "MaaFWRunnerEnvironment",
    "build_runner_environment",
    "environment_from_borrow",
    "lease_fields",
    "worker_run_plan",
]
