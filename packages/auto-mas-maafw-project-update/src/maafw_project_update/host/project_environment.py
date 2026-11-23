#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team

#   This file is part of AUTO-MAS.

#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of the
#   License, or (at your option) any later version.

#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
#   Affero General Public License for more details.

#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.

"""项目运行环境的准备与确认（宿主侧，项目更新这一块）。

「确认运行环境」= 在项目目录上备好 MaaFramework 运行池与 agent 环境（agent 环境插件的 ``prepare``
服务），成功后写环境缓存、给视图记 ``envConfirmedFor``。运行前 / 运行后确认、切换后确认、同组传播后
的后台确认都经 ``env_confirm`` 取到这里的 :func:`prepare_project_environment_sync`（``env_confirm`` 按
模块属性取，测试可以在这里打补丁）。更新前预检改走 agent 环境的 ``trial`` 服务（``precheck.py``）。

这个函数在工作线程里跑：经线程桥（``agent_env_client``）调 ``env_lookup`` 与 ``prepare_*``，线程桥由
``env_confirm.resolve_prepare_environment`` 在事件循环上取好（:data:`_bridge`），没有时用插件启用时
记下的事件循环。日志沿用「MFW 内置运行」这个 logger 名。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from auto_mas_core.host.core import Config
from auto_mas_core.host.utils import get_logger

from maafw_project_update.host import agent_env_client
from maafw_project_update.host.embedded_project import (
    mark_env_confirmed,
    read_view_marker,
)

logger = get_logger("MFW 内置运行")

#: 「报错照跑」放行时那一行（原文不变）。
LENIENT_PASS_LOG = (
    "运行环境检查没通过、按「报错照跑」放行，这次不记为「运行环境已就绪」，"
    "下次运行前再查"
)

#: 调用方在事件循环上取好的线程桥（``env_confirm`` 在工作线程里调本函数前设好）。
_bridge: ContextVar[agent_env_client.Bridge | None] = ContextVar(
    "maafw_project_update_env_bridge", default=None
)


def prepare_project_environment_sync(
    project_path: Path,
    cancel_event: threading.Event,
    send_log: Callable[[str], None],
    *,
    agent_env_root: Path | None = None,
    store_cache: bool = True,
    proxy_url: str | None = None,
    lenient_health_check: bool = False,
    health_warnings_out: list[str] | None = None,
) -> bool:
    """在工作线程里备好这个项目的运行环境，返回是否真做了准备。

    ``health_warnings_out``：给了就把「报错照跑」放行的原因追加进去，调用方据此决定收尾
    那句日志怎么写（返回值的含义不变，其它调用方不受影响）。

    先比指纹：项目没更新过、上次准备的环境也还在盘上，就只是一次哈希加
    几个 stat，直接跳过。

    更新事务的提交前预检原先也走这里（``agent_env_root`` 指池根下的预检目录、``store_cache=False``）；
    现在由 agent 环境的 ``trial`` 服务做同一条流水线（``precheck.py``），给了 ``agent_env_root`` 就报
    ``NotImplementedError``。手动更新的 API 路径没有 manager 实例，也用同一份逻辑。

    ``proxy_url`` 是托管级解析出来的代理（``None`` 表示没解析过，沿用
    全局），给池里的 uv / pip 与 agent venv 的安装用。

    ``lenient_health_check``：项目自带 Python 的健康检查「报错照跑」，只有运行前 / 运行后的
    环境确认（``_ensure_project_environment``）传；预检、手动更新、同组传播后的确认都不传
    （缺省严格，见 ``agent_env.prepare_agent_envs``）。放行过的这次不写环境缓存、不记
    ``envConfirmedFor``：下次照样重查，编辑页也不会因此显示「已就绪」。
    """

    if agent_env_root is not None:
        # 预检的一次性 agent 目录归 agent 环境的 ``trial`` 服务放、删（``precheck.py``）；
        # ``prepare`` 服务不收自定的 agent 目录，这里不能悄悄建进正式根。
        raise NotImplementedError(
            "运行环境预检改由 agent 环境的 trial 服务做，不再收 agent_env_root"
        )
    bridge = _bridge.get() or agent_env_client.fallback_bridge()

    # 视图挂的载荷在算指纹之前记下：确认成功后只给这个载荷记 ``envConfirmedFor``
    # （调用方持有视图预约，期间换不了；来源目录 / staging 没有标记，不记）。
    marker = read_view_marker(project_path) if store_cache else None
    confirmed_for = str(marker["payload"]) if marker is not None else None

    def _confirmed() -> None:
        if confirmed_for is None:
            return
        try:
            mark_env_confirmed(project_path, confirmed_for)
        except OSError as exc:
            logger.warning(f"MFW 记录运行环境确认失败（下次运行前再确认）：{exc}")

    # 指纹与缓存（agent 环境的 ``env_lookup``）：项目没更新过、上次准备的环境也还在盘上就跳过。
    lookup = agent_env_client.raise_for_failure(
        agent_env_client.call_threadsafe(
            bridge, "env_lookup", {"project_path": str(project_path)}
        )
    )
    if lookup.get("cached") is not None:
        _confirmed()
        return False

    # 读 interface、解析运行池路由、进代理作用域、准备，都在 agent 环境的 ``prepare`` 作业里，先后
    # 与原先相同；代理给最终生效值（没解析过就跟随全局）。写环境缓存也由作业做（有「报错照跑」
    # 放行的原因时不写），用这里的指纹兜底。
    request: dict[str, Any] = {
        "project_path": str(project_path),
        "proxy_url": proxy_url if proxy_url is not None else Config.proxy_url,
        "lenient_health_check": bool(lenient_health_check),
        "store_cache": bool(store_cache),
        "fallback_fingerprint": lookup.get("fingerprint"),
    }
    result = agent_env_client.raise_for_failure(
        agent_env_client.run_job_threadsafe(
            bridge,
            "prepare",
            request,
            on_event=agent_env_client.log_events(send_log),
            cancel_event=cancel_event,
        )
    )
    health_warnings = [str(item) for item in result.get("health_warnings") or ()]
    if health_warnings:
        if health_warnings_out is not None:
            health_warnings_out.extend(health_warnings)
        send_log(LENIENT_PASS_LOG)
        return True
    if store_cache:
        _confirmed()
    return True


__all__ = ["prepare_project_environment_sync"]
