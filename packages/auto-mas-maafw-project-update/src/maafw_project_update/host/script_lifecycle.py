#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""复制、删除托管时的 MFW 视图与运行池策略（给专项的托管生命周期钩子调）。

搬自宿主 ``app/task/MaaFW/seams/script_lifecycle.py``，行为不变。宿主内置时由配置回调
（``ScriptConfigHandler`` 的 ``clone_script`` / ``cleanup_script_files`` / ``after_script_removal``）调；
插件形态下由专项覆盖 ``ScriptAdapterPlugin`` 的钩子后调这里：

- ``on_script_cloned(source, target)`` → :func:`clone_script`（``owner`` 传本专项登记的属主名）；
- ``on_script_removed(script_id)`` → :func:`cleanup_script_files`，再 :func:`after_script_removal`。

视图不放在 ``data/<uid>/`` 下（避免进配置备份的整目录快照），所以宿主删 ``data/<uid>`` 时不会顺手删它，
要在这里删。
"""

from __future__ import annotations

import asyncio
from typing import Any

from auto_mas_core.host.utils import get_logger

from maafw_project_update.host.embedded_project import (
    FollowSourceCloneUnavailable,
    clone_embedded_copy,
    embedded_project_dir,
    is_source_form,
    remove_tree,
    view_owner,
)
from maafw_project_update.host.project_path import (
    release_project_path,
    try_reserve_project_path,
)

logger = get_logger("配置管理")


async def clone_script(source: Any, target: Any, *, owner: str | None = None) -> None:
    """复制时物化源载荷；失败留待运行前重建，不影响已提交的脚本复制。

    开发者模式不随复制继承，目标挂源原渠道组的 latest。组里没有正式载荷，
    或源为源码形态时先不建视图，首次运行按来源目录导入；来源也不在时沿用
    缺视图的同来源兄弟 / 已登记版本重建路径。新视图当场记下目标托管的属主（``owner``，
    由复制这个托管的属主声明）。
    """

    await target.update(
        type(target).model_validate({"Embedded": {"FollowSource": False}}),
        check_visibility=False,
    )
    group_channel = str(source.Update.Channel or "stable")
    source_form = is_source_form(source)

    target_key = await try_reserve_project_path(embedded_project_dir(str(target.uid)))
    if target_key is None:
        return
    try:
        await asyncio.to_thread(
            lambda: clone_embedded_copy(
                source_script_id=str(source.uid),
                target_script_id=str(target.uid),
                group_channel=group_channel,
                source_form=source_form,
                owner=owner,
            )
        )
    except FollowSourceCloneUnavailable as exc:
        logger.info(f"复制托管时先不建视图，第一次运行前按来源目录导入: {exc}")
    except Exception as exc:  # noqa: BLE001 - 失败下次运行会按来源 / 载荷重建
        logger.warning(f"复制托管时建视图失败，将按需重建: {exc}")
    finally:
        await release_project_path(target_key)


def after_script_removal() -> None:
    """删除提交后启动运行池对账，不拖慢删除响应。"""

    from maafw_project_update.host.live_projects import reconcile_in_background

    reconcile_in_background("script-deleted")


async def cleanup_script_files(script_id: str, *, owner: str | None = None) -> None:
    """删除不在 ``data/<uid>/`` 下的 MFW 视图。

    由删掉这个托管的属主（``owner``）声明：视图上记着别的属主时不删、记一句（那份视图不归它）。
    """

    embedded_copy = embedded_project_dir(script_id)
    if not embedded_copy.exists():
        return
    if owner is not None:
        recorded = await asyncio.to_thread(view_owner, embedded_copy)
        if recorded is not None and recorded[0] != owner:
            logger.warning(
                f"删除托管 {script_id} 时视图记着属主 {recorded[0]}（不是 {owner}），不删: "
                f"{embedded_copy}"
            )
            return
    await asyncio.to_thread(remove_tree, embedded_copy)


__all__ = ["after_script_removal", "cleanup_script_files", "clone_script"]
