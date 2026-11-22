"""账号流程自己持有的 ADB 设备缓存，以及开模拟器前定游戏包名。

从运行积木 ``maafw_runner.host.device_config`` 切片搬来（MFW 服务化）：这三样只在专项进程里用——
``MaaFWAdbDeviceState`` 是纯缓存（控制档案改存运行服务 ``device_adb_config`` 回的字典），
``choose_game_package`` 只写账号日志（它用的 ``resolve_game_package`` 在解析库），``optional_int``
是 4 行小函数（运行积木内部仍用自己那份）。设备配置本身由运行服务的 ``device_*`` 操作算。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maafw_interface.runner.game_package import resolve_game_package
from maafw_interface.runner.models import MaaFWRunPlan

if TYPE_CHECKING:
    from app.models.emulator import DeviceInfo

Log = Callable[[str], None]


@dataclass
class MaaFWAdbDeviceState:
    """调用方持有的 ADB 设备缓存：同一次模拟器启动内不重复解析。

    ``address`` / ``device_info`` 随这次启动拿到；``profile`` 里雷电的 extras 带着这次启动的
    dnplayer pid，关掉模拟器后都要清（:meth:`forget_emulator_launch`）。``adb_path`` 与哪次
    启动无关，关模拟器不清。``profile`` 是运行服务 ``device_adb_config`` 回的控制档案字典
    （``{"emulator_type", "screencap_extra", "input_extra", "config"}``），下次原样交回。
    """

    address: str | None = None
    device_info: DeviceInfo | None = None
    adb_path: str | None = None
    profile: dict[str, Any] | None = None

    def forget_emulator_launch(self) -> None:
        # 地址是随这次启动缓存的，关掉后下一轮要重新开、重新拿。
        self.address = None
        self.device_info = None
        # 雷电截图增强的 extras 里带着这次启动的 dnplayer pid；重开后还用旧 pid，
        # MaaFW 建不出截图实例（Failed to create ld inst），这一轮当场 connect 失败。
        self.profile = None


async def choose_game_package(
    manual_package: Any, plan: MaaFWRunPlan | None, *, log: Log
) -> str:
    """这次要不要顺带把游戏拉起来，拉哪个包。返回空串表示只开模拟器。

    ``manual_package`` 是脚本配置 ``Game.PackageName`` 的原值。填了就以它为准：从项目里认
    包名是启发式的（``StartApp`` 只是约定，不是 interface 规格里的字段），用户必须有办法
    推翻它。

    认不出来不是错误——很多项目本来就自己在 pipeline 里开游戏。但要让用户看得见
    为什么没启动，否则「填了没反应」和「没填也没反应」在界面上长得一模一样。
    """
    manual = str(manual_package or "").strip()
    if manual:
        log(f"游戏包名: {manual}（脚本配置）")
        return manual

    if plan is None:
        return ""

    resolution = await asyncio.to_thread(
        resolve_game_package,
        [
            Path(item.resolved)
            for item in plan.resource.paths
            if item.exists and item.isDir
        ],
        [task.pipelineOverride for task in plan.tasks if task.pipelineOverride],
    )

    if resolution.reason == "resolved":
        log(f"游戏包名: {resolution.package}（从项目识别）")
        return resolution.package

    if resolution.reason == "ambiguous":
        log(
            f"项目里识别到多个游戏包名（{'、'.join(resolution.candidates)}），"
            "无法确定用哪个，本次不随模拟器启动游戏；"
            "需要的话在托管管理页填写游戏包名"
        )
    else:
        log(
            "未能从项目里识别出游戏包名，本次不随模拟器启动游戏；"
            "需要的话在托管管理页填写游戏包名"
        )
    return ""


def optional_int(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["Log", "MaaFWAdbDeviceState", "choose_game_package", "optional_int"]
