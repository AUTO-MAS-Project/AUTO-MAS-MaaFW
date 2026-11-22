#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""MFW 项目更新服务插件：13 个 ``/maafw/*`` 端点、托管属主登记、启动期与每日维护。

规则 L（拆分契约 §2.0）：本模块和它在模块顶层的整条导入链里不出现别的插件包（三块积木、三个
专项）；agent 环境插件的模块只在函数体内导入。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from auto_mas_core import Config, ExtensionPlugin
from auto_mas_core.host.utils import get_logger

from .api.routes import api_router as _api_router
from .host import owners

PACKAGE_NAME = "auto-mas-maafw-project-update"
PACKAGE_VERSION = "0.1.0"

# 联调保护：设为 1 时插件不跑任何维护清理，也不注入「托管完整加载」信号（据此判断「不在了」的
# 清理因此一律跳过）。
NO_CLEANUP_ENV = "AUTO_MAS_MFW_NO_CLEANUP"

# 启动期维护：每 5 秒看一次托管是否完整加载，10 分钟还没加载完就放弃这一轮。
_LOADED_POLL_SECONDS = 5.0
_LOADED_WAIT_SECONDS = 600.0
# 原生日志清理的间隔（原宿主每日定时器里的一步）。
_NATIVE_LOG_INTERVAL_SECONDS = 24 * 3600.0

logger = get_logger("MFW 项目更新插件")


class Plugin(ExtensionPlugin):
    """项目副本、视图、导入更新与维护清理；三个专项经 ``owner.register`` 登记属主。"""

    requires = ("maafw.agent_env.v1",)
    provides_services = {
        "maafw.project.v1": "call",
        "maafw.project_update.v1": "call",
    }
    api_router = _api_router

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # (属主名, 服务名) → 取入口的函数：同一属主重复登记时交回同一个函数（owners 认 is）
        self._resolvers: dict[tuple[str, str], Callable[[], Any]] = {}
        self._signal_injected = False

    # -- 服务 -----------------------------------------------------------------

    async def call(self, op: str, /, **kwargs: Any) -> Any:
        """``maafw.project.v1`` / ``maafw.project_update.v1`` 的分发入口。"""

        if op == "version":
            return {"package": PACKAGE_NAME, "version": PACKAGE_VERSION}
        if op == "owner.register":
            self._register_owner(str(kwargs["name"]), str(kwargs["service"]))
            return None
        if op == "owner.unregister":
            name = str(kwargs["name"])
            owners.unregister_owner(name)
            for key in [key for key in self._resolvers if key[0] == name]:
                del self._resolvers[key]
            return None
        raise ValueError(f"未知操作: {op}")

    def _register_owner(self, name: str, service: str) -> None:
        resolve = self._resolvers.get((name, service))
        if resolve is None:

            def resolve() -> Any:
                # 每次现取属主服务；取不到就交回 None，owners 当成「属主没登记」
                entry = self.services.get(service)
                if entry is None:
                    return None
                return entry()

        owners.register_owner(name, resolve=resolve)
        self._resolvers[(name, service)] = resolve

    # -- 生命周期 ---------------------------------------------------------------

    async def on_enable(self) -> None:
        if os.environ.get(NO_CLEANUP_ENV) == "1":
            logger.warning(f"{NO_CLEANUP_ENV}=1：MFW 维护清理整个跳过")
            return
        if getattr(Config, "maafw_maintenance", None) is not None:
            # 宿主还在自己建维护（没切到让位分支）：两套维护同时清 data/mfw 可能误删
            logger.warning("宿主仍内置 MFW 维护，插件不再起维护，也不注入托管加载信号")
            return
        owners.set_loaded_signal(Config.script_config_loaded_intact)
        self._signal_injected = True

        from .host.maintenance import MaaFWMaintenanceService

        service = MaaFWMaintenanceService(
            scripts_loaded_intact=Config.script_config_loaded_intact,
            retention_days=lambda: Config.setting.Function.HistoryRetentionTime,
            process_started_at=_process_started_at(),
        )
        self.background_tasks.spawn(
            lambda: _maintenance_loop(service), retain_result=False
        )

    async def on_disable(self) -> None:
        # 后台维护随 background_tasks 组由宿主取消；这里只撤掉注入的信号
        if self._signal_injected:
            owners.set_loaded_signal(None)
            self._signal_injected = False


def _process_started_at() -> float:
    """宿主进程的启动时刻（旧副本迁移据此判断「本次启动之前」）。"""

    # SDK 没有这一项；0.1.0 在函数体内直接取宿主模块的私有常量
    from app.core.config.manager import _PROCESS_STARTED_AT

    return float(_PROCESS_STARTED_AT)


async def _maintenance_loop(service: Any) -> None:
    """启动期维护跑一遍（原 ``main.py`` 的七步顺序），之后每 24 小时清一次原生日志。"""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _LOADED_WAIT_SECONDS
    while not Config.script_config_loaded_intact():
        if loop.time() >= deadline:
            logger.warning("托管配置 10 分钟内没有完整加载，跳过这一轮 MFW 启动期维护")
            break
        await asyncio.sleep(_LOADED_POLL_SECONDS)
    else:
        await _startup_maintenance(service)
    while True:
        try:
            await service.clean_native_debug_logs()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 一次清理失败不该停掉以后的
            logger.exception("MaaFW 原生日志清理失败")
        await asyncio.sleep(_NATIVE_LOG_INTERVAL_SECONDS)


async def _startup_maintenance(service: Any) -> None:
    """照原 ``main.py`` 的 ``_maafw_startup_maintenance`` 顺序跑；失败记一行，下次启动再试。"""

    try:
        # 老副本一次性采纳成「载荷 + 视图」，再跑依赖终态布局的各项回收
        await service.migrate_embedded_copies_to_payloads()
        await service.tag_view_owners()
        await service.clean_embedded_copies()
        # 先清副本，再把应保留的视图交给 agent 环境对账：副本删掉以后它引用的隔离 venv
        # 才会变成无人引用
        await service.clean_agent_venvs()
        await service.clean_runtime_blobs()
        await service.clean_update_cache()
        # 副本清理之后：副本没了，它的 binding / runtime 才会变成无人引用
        await service.clean_runtime_pool()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - 与宿主原先同一口径
        logger.exception("MFW 启动期维护失败，下次启动再试")


__all__ = ["Plugin"]
