"""worker 子进程的导入路径（插件包新写）。

宿主时代 worker 靠 ``PYTHONPATH`` 里的宿主源码根导入 ``app.task.MaaFW.tools.core``。拆成插件包后，
worker 要导入的是四个包：本包（``maafw_runner.core``）、agent 环境积木（``maafw_agent_env.core``）
和两块库。它们装在哪由安装方式决定（本地源码布局下各在自己的 ``src``，发行包布局下都在
``plugins/pypi/site-packages``），所以按各包的位置现算父目录，去重后交给 worker。

agent 环境那一份由借环境结果的 ``worker_paths`` 带回（agent 环境按自己的 ``__file__`` 算，MFW 服务化
实施方案 §5）；宿主侧不导入 ``maafw_agent_env``。没给时退回 ``importlib.util.find_spec`` 找包位置，
不执行对方的包。

运行池隔离 venv 里只有 ``BASE_RUNTIME_PACKAGES``，不装这四个包；``PYTHONPATH`` 里的
binding 目录仍排在最前（``host.environment.build_runner_environment``）。
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path

# worker 导入闭包里的四个顶层包（拆分文档 §4）
WORKER_PACKAGES = ("maafw_runner", "maafw_agent_env", "maafw_interface", "maafw_native")
_AGENT_ENV_PACKAGE = "maafw_agent_env"


def _package_parent(name: str) -> Path | None:
    module = sys.modules.get(name)
    package_file = getattr(module, "__file__", None) if module is not None else None
    if not package_file:
        spec = importlib.util.find_spec(name)
        package_file = spec.origin if spec is not None else None
    if not package_file:
        return None
    return Path(package_file).resolve().parent.parent


def worker_import_paths(
    agent_env_paths: Iterable[str | Path] | None = None,
) -> list[Path]:
    """四个包各自所在的父目录（去重、保持顺序）。

    ``agent_env_paths`` 是借环境结果的 ``worker_paths``，排在 agent 环境原来的位置；不给时现找。
    """

    paths: list[Path] = []

    def add(path: Path | None) -> None:
        if path is not None and path not in paths:
            paths.append(path)

    for name in WORKER_PACKAGES:
        if name == _AGENT_ENV_PACKAGE and agent_env_paths is not None:
            for item in agent_env_paths:
                add(Path(item).resolve())
            continue
        add(_package_parent(name))
    return paths
