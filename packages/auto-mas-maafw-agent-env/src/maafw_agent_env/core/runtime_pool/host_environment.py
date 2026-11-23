"""MFW 专项各子进程共用的宿主环境隔离口径：从原生库识别库 ``maafw_native.subprocess_env`` 再导出。

实现整份搬进了 ``maafw_native.subprocess_env``（运行的宿主侧拼 worker 环境、项目更新都要用，
放在两块库里谁都能导入，不必经本插件）。这里原样再导出原来的全部名字，本包内部与旧调用方的导入
不用改；代理作用域是那个模块的线程局部状态，两边读写的是同一份。
"""

from __future__ import annotations

from maafw_native.layout import PROJECT_PYCACHE_DIR_NAME
from maafw_native.subprocess_env import (
    _PYCACHE_RELATIVE_BUDGET as _PYCACHE_RELATIVE_BUDGET,
)
from maafw_native.subprocess_env import (
    _SUBPROCESS_PROXY_STATE as _SUBPROCESS_PROXY_STATE,
)
from maafw_native.subprocess_env import _WINDOWS_MAX_PATH as _WINDOWS_MAX_PATH
from maafw_native.subprocess_env import (
    ISOLATED_HOST_KEYS,
    LOOPBACK_NO_PROXY_HOSTS,
    PASSTHROUGH_PYTHON_KEYS,
    PROXY_ENVIRONMENT_KEYS,
    apply_proxy_environment,
    current_subprocess_proxy,
    is_isolated_host_key,
    project_pycache_prefix,
    pycache_prefix_fits,
    set_project_pycache_prefix,
    strip_host_python_environment,
    subprocess_proxy_scope,
)
from maafw_native.subprocess_env import (
    _windows_long_paths_enabled as _windows_long_paths_enabled,
)

__all__ = [
    "ISOLATED_HOST_KEYS",
    "LOOPBACK_NO_PROXY_HOSTS",
    "PASSTHROUGH_PYTHON_KEYS",
    "PROJECT_PYCACHE_DIR_NAME",
    "PROXY_ENVIRONMENT_KEYS",
    "apply_proxy_environment",
    "current_subprocess_proxy",
    "is_isolated_host_key",
    "project_pycache_prefix",
    "pycache_prefix_fits",
    "set_project_pycache_prefix",
    "strip_host_python_environment",
    "subprocess_proxy_scope",
]
