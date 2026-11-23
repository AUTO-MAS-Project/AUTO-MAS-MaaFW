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

"""新版本登记前的运行环境预检：挂在更新流程的 ``post_validate`` 上。

MaaEnd v2.29.0 打包了 MaaFramework v5.14.0-beta.1，binding 被钉成
``maafw==5.14.0b1`` 而 PyPI 上没有——更新成功、环境建不出来、任务每次必挂。
所以新载荷在 staging 里建好、登记之前先**真建**一次运行环境（不 dry-run；把自带
Python 里的 binding 钉回原生库版本也就发生在这一步，写的是 staging）：建不出来
就丢掉 staging、所有视图继续跑当前版本，并按谱系 + 目标版本写备忘
（``precheck_memo.py``），之后每次运行前由 ``precheck_gate.py`` 按失败类别决定要不要重试
（缺 binding 轻探一次；网络类与其它原因各自冷却一段时间后再试）。

环境建好之后再对 Python agent 做一次导入静态检查（``agent_env/import_check.py``）：
MaaFgo v2.0.03 漏装了 ``agent/battle/runtime/``，解释器能 ``import maa``，agent 一启动却
``ModuleNotFoundError``。启动时必然 import 的项目模块不在就同样丢弃新版本；第三方包缺失等
只记日志。检查自身出任何意外都放行（宁可漏报，不可误拒）。

建环境、导入检查、临时 agent 目录的放置与回收归 agent 环境一侧（agent 环境插件的 ``trial`` 服务，
经线程桥调）；这里只查新版本自带的原生库能不能加载、记失败原因与备忘、构造回调。
回调跑在工作线程里，不拿锁、不 await。运行前自动更新
（``project_session``）与手动更新（``/maafw/update``）共用同一份逻辑，两边只在
「要不要读备忘」上不同（手动不读，见 precheck_gate）。
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, MutableMapping
from pathlib import Path
from typing import Any

from auto_mas_core.host.core import Config
from auto_mas_core.host.utils import get_logger

from maafw_project_update.core.project_update.precheck_memo import (
    classify_precheck_failure,
    write_runtime_precheck,
)
from maafw_project_update.host import agent_env_client

logger = get_logger("MFW 更新预检")

#: 新版本的 agent 启动时 import 的项目模块不在（文案分支用；值同 agent 环境
#: ``import_check.KIND_AGENT_MODULE_MISSING``，也是 ``trial`` 服务的失败 code）。
KIND_AGENT_MODULE_MISSING = "agent_module_missing"


def _resolve_requirement(project_path: Path) -> str | None:
    """项目此刻（已是新版本）要钉的 maafw requirement；只进备忘字段。"""

    try:
        # 要读项目自带的 DLL，逻辑在原生库识别库（tools/core/native）里；只在真要写备忘时才导入。
        from maafw_native.requirement import (
            resolve_project_maafw_requirement,
        )

        return resolve_project_maafw_requirement(project_path)
    except Exception:  # noqa: BLE001 - 解析不出来就记 "maafw"，不盖住预检原因
        return None


class MaaFWNativeLoadError(RuntimeError):
    """新版本里 runner 要用的 MaaFramework 原生库在干净进程里都加载不了。"""


def check_staging_native_runtime(root: Path, send_log: Callable[[str], None]) -> None:
    """在独立子进程里加载一次 staging 里 runner 会用的 ``MaaFramework.dll``；确定加载不了
    就 raise。

    agent 那一侧的检查用的是项目自带 Python 里的 maafw，碰不到 runner 用的这份原生库：
    MAA_bbb v1.13.20 的差量更新把 runner 换到了只有几个 DLL 的 ``runtimes/win-x64``，预检
    照样通过，切过去以后每次运行都报 ``Could not find module ... (or one of its
    dependencies)``。只在 Windows 上查；找不到原生库、子进程起不来或超时都放行
    （宁可漏报，不可误拒），只有子进程明确报「加载失败」才拒。
    """

    if os.name != "nt":
        return
    try:
        from maafw_native.project_runtime import (
            NATIVE_LOAD_FAILED,
            NATIVE_LOAD_OK,
            probe_native_runtime_load,
            project_maafw_runtime_path,
        )

        runtime = project_maafw_runtime_path(root)
    except Exception as exc:  # noqa: BLE001 - 定位不了就不下结论
        logger.warning(f"定位新版本的 MaaFramework 原生库失败，放行：{exc}")
        return
    if runtime is None:
        return
    verdict, detail = probe_native_runtime_load(runtime)
    try:
        location = runtime.relative_to(root).as_posix()
    except ValueError:
        location = str(runtime)
    if verdict == NATIVE_LOAD_FAILED:
        raise MaaFWNativeLoadError(
            f"新版本自带的 MaaFramework（{location}/）加载不了：{detail}。"
            "多半是这个目录里缺了依赖的 DLL"
        )
    if verdict != NATIVE_LOAD_OK:
        logger.warning(f"MaaFramework 原生库加载检查没能完成，放行：{detail}")
        send_log("[原生库检查] 没能完成，跳过")
        return
    send_log(f"[原生库检查] {location}/MaaFramework.dll 加载正常")


def run_trial(
    root: Path,
    *,
    bridge: agent_env_client.Bridge,
    pool_root: str | Path,
    proxy_url: str | None,
    cancel_event: threading.Event,
    send_log: Callable[[str], None],
    previous_version: str | None = None,
) -> None:
    """在 ``root``（staging）上真建一次运行环境（不写环境缓存）再查 Python agent 的导入：agent 环境的
    ``trial`` 作业，经线程桥在工作线程里调。建不出来或缺项目模块就 raise（文字是原文）。

    一次性的 agent 目录放在 ``pool_root`` 下的预检根里，由作业放、作业删。``proxy_url`` 是托管级解析
    出的代理，``None`` 表示没解析过、沿用全局。``cancel_event`` 置位后让作业停下，照常等它结束。
    """

    request = {
        "project_path": str(root),
        "runtime_pool_root": str(pool_root),
        "proxy_url": proxy_url if proxy_url is not None else Config.proxy_url,
        "previous_version": previous_version,
    }
    agent_env_client.raise_for_failure(
        agent_env_client.run_job_threadsafe(
            bridge,
            "trial",
            request,
            on_event=agent_env_client.log_events(send_log),
            cancel_event=cancel_event,
        )
    )


def build_precheck_validator(
    *,
    bridge: agent_env_client.Bridge,
    proxy_url: str | None,
    cancel_event: threading.Event,
    send_log: Callable[[str], None],
    pool_root: str | Path,
    failure: MutableMapping[str, Any],
    previous_version: str | None = None,
    project_name: str | None = None,
    memo_path_for: Callable[[str], Path] | None = None,
) -> Callable[[Path], bool]:
    """构造 ``post_validate`` 回调（收新载荷的 staging 路径）。

    建环境与导入检查是 agent 环境的 ``trial`` 作业（:func:`run_trial`，线程桥 ``bridge`` 在事件循环上
    取好；``pool_root`` 是运行池根，预检根在它下面）。失败时把 ``{targetVersion, requirement, kind, reason, …}``
    写进 ``failure``，按 ``memo_path_for(目标版本)`` 落备忘（谱系 + 版本，组共有），
    然后原样 raise 让原因进异常文本；用户取消（``cancel_event`` 已置位）时既不写
    备忘也不填 ``failure``。D4：不按「requirement 为 None」短路，一律走同一套准备。
    """

    def validate(root: Path) -> bool:
        send_log("正在检查新版本的运行环境（准备不出来就放弃这次更新，继续用当前版本）")
        try:
            # 原生库加载只要一两秒，放在建环境前面：加载不了就不必再建
            check_staging_native_runtime(root, send_log)
            # 已取消就不再查导入：核心包随后按取消收尾（作业里看令牌）
            run_trial(
                root,
                bridge=bridge,
                pool_root=pool_root,
                proxy_url=proxy_url,
                cancel_event=cancel_event,
                send_log=send_log,
                previous_version=previous_version,
            )
        except Exception as exc:
            if cancel_event.is_set():
                raise
            info = classify_precheck_failure(
                root, exc, requirement=_resolve_requirement(root)
            )
            if getattr(exc, "code", None) == KIND_AGENT_MODULE_MISSING:
                # 备忘里仍按 other 记（冷却一天才自动再试），这里只给文案分支用
                info["kind"] = KIND_AGENT_MODULE_MISSING
            if previous_version:
                info["previousVersion"] = str(previous_version)
            if project_name:
                info["projectName"] = str(project_name)
            failure.clear()
            failure.update(info)
            if memo_path_for is not None and info.get("targetVersion"):
                try:
                    write_runtime_precheck(
                        memo_path_for(str(info["targetVersion"])), info
                    )
                except Exception as memo_error:  # noqa: BLE001
                    logger.warning(f"写运行环境预检备忘失败：{memo_error}")
            raise
        send_log("新版本运行环境检查通过")
        return True

    return validate


__all__ = [
    "KIND_AGENT_MODULE_MISSING",
    "MaaFWNativeLoadError",
    "build_precheck_validator",
    "check_staging_native_runtime",
    "run_trial",
]
