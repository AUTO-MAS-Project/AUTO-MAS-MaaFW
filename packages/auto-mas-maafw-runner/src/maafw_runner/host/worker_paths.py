"""worker 子进程的导入路径（插件包新写）。

宿主时代 worker 靠 ``PYTHONPATH`` 里的宿主源码根导入 ``app.task.MaaFW.tools.core``。拆成插件包后，
worker 要导入的是四个包：本包（``maafw_runner.core``）、agent 环境积木（``maafw_agent_env.core``）
和两块库。它们装在哪由安装方式决定（本地源码布局下各在自己的 ``src``，发行包布局下都在
``plugins/pypi/site-packages``），所以按各包的 ``__file__`` 现算父目录，去重后交给 worker。

运行池隔离 venv 里只有 ``BASE_RUNTIME_PACKAGES``，不装这四个包；``PYTHONPATH`` 里的
binding 目录仍排在最前（``core.runner.environment.build_runner_environment``）。
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

# worker 导入闭包里的四个顶层包（拆分文档 §4）
WORKER_PACKAGES = ("maafw_runner", "maafw_agent_env", "maafw_interface", "maafw_native")


def worker_import_paths() -> list[Path]:
    """四个包各自所在的父目录（去重、保持顺序）。"""

    paths: list[Path] = []
    for name in WORKER_PACKAGES:
        package_file = getattr(import_module(name), "__file__", None)
        if not package_file:
            continue
        parent = Path(package_file).resolve().parent.parent
        if parent not in paths:
            paths.append(parent)
    return paths
