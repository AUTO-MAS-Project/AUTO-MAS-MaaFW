from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from auto_mas_core.host.utils import get_logger

from maafw_project_update.core.path_key import resolved_path_str

# 账号运行交回预约时的告警沿用任务类的 logger 名（原先就在 runner_task 里记；现由项目服务
# ``run_release`` 取用）
_logger = get_logger("MaaFW 插件自动代理")

# 用户点停止后，等核对 / 清理线程收尾的上限：到点就不等了，预约交给它完成后再放。交回预约已搬到
# 专项共用库（``maafw_adapter_kit.services.release_run_reservation``），那边的同名常量照这个值。
RELEASE_CHECK_CANCEL_GRACE_SECONDS = 30.0

_ACTIVE_PROJECT_PATHS: set[str] = set()
_ACTIVE_PROJECT_PATHS_LOCK = threading.Lock()


def normalize_project_path(path: str | Path) -> str:
    """Return the process-wide key used by update and execution reservations.

    ``resolve()`` 在别的线程正建 / 换目录时会交回 ``\\\\?\\`` 前缀，先去掉（``core.path_key``），
    否则同一个目录算出两个键。
    """

    return os.path.normcase(resolved_path_str(path)).casefold()


async def try_reserve_project_path(path: str | Path) -> str | None:
    """Reserve a project directory without blocking the event loop.

    The critical section only mutates an in-memory set, so a process-wide
    threading lock also keeps separate event loops/worker threads consistent.
    Callers deliberately fail fast instead of waiting: AUTO-MAS already skips a
    second MaaFW run for the same external directory.
    """

    key = normalize_project_path(path)
    with _ACTIVE_PROJECT_PATHS_LOCK:
        if key in _ACTIVE_PROJECT_PATHS:
            return None
        _ACTIVE_PROJECT_PATHS.add(key)
    return key


async def release_project_path(key: str | None) -> None:
    release_project_path_sync(key)


def try_reserve_project_path_sync(path: str | Path) -> str | None:
    """同一张表的同步版：给已经在工作线程里跑的服务层代码用（它拿不到事件循环）。"""

    key = normalize_project_path(path)
    with _ACTIVE_PROJECT_PATHS_LOCK:
        if key in _ACTIVE_PROJECT_PATHS:
            return None
        _ACTIVE_PROJECT_PATHS.add(key)
    return key


def release_project_path_sync(key: str | None) -> None:
    if not key:
        return
    with _ACTIVE_PROJECT_PATHS_LOCK:
        _ACTIVE_PROJECT_PATHS.discard(key)


# 正在更新的视图（计数：手动更新整段标一次，里面的 run_view_update 再标一次）。
# 只是给「为什么拿不到预约 / 为什么现在不能更新」配文案用的旁证，不参与预约与谱系锁。
_UPDATING_PROJECT_PATHS: dict[str, int] = {}


def begin_project_updating(path: str | Path) -> str:
    """把该视图登记为「正在更新」，返回给 :func:`end_project_updating` 的键；可嵌套。"""

    key = normalize_project_path(path)
    with _ACTIVE_PROJECT_PATHS_LOCK:
        _UPDATING_PROJECT_PATHS[key] = _UPDATING_PROJECT_PATHS.get(key, 0) + 1
    return key


def end_project_updating(key: str) -> None:
    with _ACTIVE_PROJECT_PATHS_LOCK:
        remaining = _UPDATING_PROJECT_PATHS.get(key, 0) - 1
        if remaining > 0:
            _UPDATING_PROJECT_PATHS[key] = remaining
        else:
            _UPDATING_PROJECT_PATHS.pop(key, None)


@contextmanager
def mark_project_updating(path: str | Path) -> Iterator[None]:
    """在这段里把该视图登记为「正在更新」；可嵌套。"""

    key = begin_project_updating(path)
    try:
        yield
    finally:
        end_project_updating(key)


def is_project_updating(path: str | Path) -> bool:
    key = normalize_project_path(path)
    with _ACTIVE_PROJECT_PATHS_LOCK:
        return key in _UPDATING_PROJECT_PATHS


def is_project_path_reserved(path: str | Path) -> bool:
    """这个目录此刻有没有被预约（运行、更新、导入、准备运行环境）；只看不占。"""

    key = normalize_project_path(path)
    with _ACTIVE_PROJECT_PATHS_LOCK:
        return key in _ACTIVE_PROJECT_PATHS


def busy_project_counts() -> tuple[int, int]:
    """``(被预约的目录数, 正在更新的目录数)``：插件停用前据此拒绝（``teardown_blockers``）。"""

    with _ACTIVE_PROJECT_PATHS_LOCK:
        return len(_ACTIVE_PROJECT_PATHS), len(_UPDATING_PROJECT_PATHS)
