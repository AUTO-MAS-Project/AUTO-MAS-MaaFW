"""worker 子进程用的 agent 环境门面（``WORKER_API_VERSION = 1``）。

运行的 worker（``python -m maafw_runner.core.runner.worker``）不在宿主进程里，够不到插件服务；
它起 agent 前要用的 agent 环境代码经这里导入，runner 的 ``core/`` 只准从本模块导入
``maafw_agent_env``（MFW 服务化实施方案 §5）。

规则：

- ``WORKER_API_VERSION`` 不变时只增不改；要破坏性改动另开 ``worker_api_v2``，旧的至少再留一个次版本。
- ``WORKER_API_VERSIONS`` 是本发行包支持的门面版本，``version`` 操作和借环境结果的 ``worker_api``
  原样回报，runner 起 worker 前核对自己用的那一版在不在。
- 本模块在 worker 里导入：只许导入 worker 本来就导入的那几个模块，不碰宿主与 SDK。
"""

from __future__ import annotations

from .agent_env import (
    prepare_agent_envs,
    project_python_agent_binary_path,
    write_agent_compat_shims,
)
from .agent_env.env import AGENT_PROGRAM_MISSING_HINT
from .agent_env.pip_constraint import (
    AGENT_PIP_CONSTRAINT_DIR_ENV,
    agent_maafw_pip_constraint,
    apply_agent_pip_constraint,
    write_agent_pip_constraint,
)

WORKER_API_VERSION = 1
#: 本发行包支持的门面版本（新开 ``worker_api_v2`` 时往这里追加）。
WORKER_API_VERSIONS: tuple[int, ...] = (WORKER_API_VERSION,)

__all__ = [
    "AGENT_PIP_CONSTRAINT_DIR_ENV",
    "AGENT_PROGRAM_MISSING_HINT",
    "WORKER_API_VERSION",
    "WORKER_API_VERSIONS",
    "agent_maafw_pip_constraint",
    "apply_agent_pip_constraint",
    "prepare_agent_envs",
    "project_python_agent_binary_path",
    "write_agent_compat_shims",
    "write_agent_pip_constraint",
]
