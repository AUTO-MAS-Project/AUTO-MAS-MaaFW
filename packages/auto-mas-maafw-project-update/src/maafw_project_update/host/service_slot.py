#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""本插件拿宿主服务解析器的槽：插件 ``on_enable`` 绑、``on_disable`` / ``on_teardown`` 解。

项目更新这一块的旧函数入口（``MaaFWProjectSession``、``prepare_project_environment_sync``、维护……）是
模块函数，手里没有插件实例；它们调 agent 环境服务、问属主服务时经这里现取解析器。绑的时候顺手记下
事件循环（插件生命周期跑在宿主的主事件循环上）：工作线程里没有现成的事件循环可取，线程桥用它。

每次调用都现取服务（``resolver.require(name)`` / ``resolver.get(name)``），不缓存服务对象。
本模块只用标准库，不导入宿主与别的插件。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

_resolver: Any | None = None
_loop: asyncio.AbstractEventLoop | None = None
_spawn: Callable[[Callable[[], Any]], Any] | None = None


def bind(
    resolver: Any,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    spawn: Callable[[Callable[[], Any]], Any] | None = None,
) -> None:
    """绑上解析器（插件的 ``self.services``）；``loop`` 缺省取当前正在跑的事件循环。

    ``spawn`` 收一个「返回协程的工厂」，起一个不属于调用方进程作用域的后台任务（插件的
    ``background_tasks.spawn``）；不给时后台任务直接在事件循环上建。
    """

    global _resolver, _loop, _spawn
    if loop is None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
    _resolver = resolver
    _loop = loop
    _spawn = spawn


def unbind(resolver: Any | None = None) -> None:
    """解绑；给了 ``resolver`` 时只在槽里还是它时才解（重载时新实例可能已经绑上）。"""

    global _resolver, _loop, _spawn
    if resolver is not None and _resolver is not resolver:
        return
    _resolver = None
    _loop = None
    _spawn = None


def resolver() -> Any | None:
    return _resolver


def loop() -> asyncio.AbstractEventLoop | None:
    return _loop


def spawner() -> Callable[[Callable[[], Any]], Any] | None:
    return _spawn


__all__ = ["bind", "loop", "resolver", "spawner", "unbind"]
