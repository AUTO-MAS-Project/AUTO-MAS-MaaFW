#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""项目更新调 agent 环境服务（``maafw.agent_env.v1.*``）的那一层。

原先这一块直接导入 agent 环境插件的模块（准备环境、预检、回收、缓存、运行池路由），现在都改成经
服务调用；口径见 MFW 服务化实施方案 §2.5、§3.1、§3.3：

- 每次调用都经 :mod:`service_slot` 现取解析器、``require`` 现取服务，不缓存服务对象；提供方暂停准入
  时由解析库 ``service_calls`` 退避重试，注册表已封、服务没登记时立即放弃。
- 事件循环上：:func:`call`（短操作）、:func:`run_job`（长操作 ``<族>_start/_poll/_stop/_close``）。
- 工作线程里（更新核心的预检回调、投影补齐的预检、同组传播后的后台确认、运行环境准备的旧入口）：
  :func:`call_threadsafe`、:func:`run_job_threadsafe` 经线程桥把每次调用交给事件循环跑，逐批事件在
  调用线程里交给回调（与原先 ``send_log`` 在工作线程里被调一致），停止令牌在两次轮询之间看。
  事件循环与进程作用域在起线程前于事件循环上用 :func:`capture_bridge` 取好；线程里每次调用都在
  事件循环上重新 ``require``。
- 服务回的失败用 :func:`raise_for_failure` 变回异常：文字是原文，类名取 ``detail.exception_type``
  （后端日志里的类型名与原先一致），原先就让异常往上抛的调用点照旧往上抛。

本模块不导入 agent 环境插件。
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from maafw_interface.service_calls import (
    CANCEL_DETACH,
    ServiceUnavailable,
    call_service,
    run_coroutine_from_thread,
    run_operation,
    service_unavailable_result,
)

from . import service_slot

#: agent 环境服务名的前缀。
AGENT_ENV = "maafw.agent_env.v1"
#: agent 环境插件拿不到、句柄失效时的固定话（实施方案 §1 第 12 条）。
UNAVAILABLE_MESSAGE = "MFW agent 环境插件已重新加载或停用，本次环境准备的结果拿不到了"
#: 线程里轮询的等待：停止令牌在两次轮询之间看，取短一点，停止不比原先慢多少。
THREAD_POLL_WAIT_SECONDS = 0.2
#: 有 ``_stop`` 的族（``reconcile`` 没有）。
_STOPPABLE = frozenset({"borrow", "prepare", "trial"})

#: 本块用到的 agent 环境操作（``requires``，实施方案 §3.3：15 个）。
REQUIRED_OPERATIONS: tuple[str, ...] = (
    "runtime_route",
    "storage_info",
    "env_lookup",
    "prepare_start",
    "prepare_poll",
    "prepare_stop",
    "prepare_close",
    "trial_start",
    "trial_poll",
    "trial_stop",
    "trial_close",
    "reconcile_start",
    "reconcile_poll",
    "reconcile_close",
    "cache_prune",
)
REQUIRES: tuple[str, ...] = tuple(f"{AGENT_ENV}.{op}" for op in REQUIRED_OPERATIONS)


class _Unbound:
    """槽还没绑（插件没启用、或已停用）：一律按服务不可用处理。"""

    accepting = True

    def require(self, name: str) -> Any:
        raise ServiceUnavailable(name, "unbound")


_UNBOUND = _Unbound()


def _resolver() -> Any:
    resolver = service_slot.resolver()
    return _UNBOUND if resolver is None else resolver


def _name(op: str) -> str:
    return f"{AGENT_ENV}.{op}"


# ---------------------------------------------------------------------------
# 失败变回异常
# ---------------------------------------------------------------------------


class AgentEnvServiceError(RuntimeError):
    """agent 环境服务回的失败（``ok: false``）；``code`` / ``detail`` 原样带着。"""

    code: str = ""
    detail: Mapping[str, Any] = {}


_ERROR_TYPES: dict[str, type[AgentEnvServiceError]] = {}


def _error_type(name: str) -> type[AgentEnvServiceError]:
    """类名与提供方那边原异常相同的子类（只为后端日志里的类型名不变）。"""

    if not name.isidentifier():
        return AgentEnvServiceError
    found = _ERROR_TYPES.get(name)
    if found is None:
        found = type(name, (AgentEnvServiceError,), {"__module__": __name__})
        _ERROR_TYPES[name] = found
    return found


def failure_error(result: Mapping[str, Any]) -> AgentEnvServiceError:
    """失败结果 → 异常：文字是 ``message`` 原文，类名取 ``detail.exception_type``。"""

    detail = result.get("detail")
    detail = detail if isinstance(detail, Mapping) else {}
    type_name = str(detail.get("exception_type") or "")
    error = _error_type(type_name)(str(result.get("message") or ""))
    error.code = str(result.get("code") or "")
    error.detail = dict(detail)
    return error


def raise_for_failure(result: Mapping[str, Any]) -> Mapping[str, Any]:
    """``ok`` 为假就抛 :func:`failure_error`；否则原样返回。"""

    if not result.get("ok"):
        raise failure_error(result)
    return result


# ---------------------------------------------------------------------------
# 事件循环上
# ---------------------------------------------------------------------------


async def call(op: str, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """调一个短操作；服务拿不到时回 ``service_unavailable``。"""

    name = _name(op)
    try:
        value = await call_service(_resolver(), name, request)
    except ServiceUnavailable as exc:
        return service_unavailable_result(exc, UNAVAILABLE_MESSAGE)
    return dict(value) if isinstance(value, Mapping) else {"ok": True, "value": value}


async def run_job(
    family: str,
    request: Mapping[str, Any] | None = None,
    *,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    cancel_rule: str = CANCEL_DETACH,
) -> dict[str, Any]:
    """跑一个长操作到结束，返回终态结果（或 ``_start`` 当场的失败 / 跳过、服务不可用）。

    调用方被取消时按 ``cancel_rule`` 收尾（解析库 ``ServiceOperation``）后重抛。
    """

    return await run_operation(
        _resolver(),
        _name(family),
        request,
        cancel_rule=cancel_rule,
        unavailable_message=UNAVAILABLE_MESSAGE,
        on_event=on_event,
    )


# ---------------------------------------------------------------------------
# 工作线程里（线程桥）
# ---------------------------------------------------------------------------

_NO_SCOPE: Any = object()


@dataclass(frozen=True)
class Bridge:
    """线程桥：事件循环与（要时）调用方的进程作用域，在起线程前于事件循环上取好。

    ``scope`` 是 :data:`_NO_SCOPE` 时不改作用域（沿用线程自己的上下文）；否则每次在事件循环上
    调服务前把 ``current_process_scope`` 设成它——与原先在事件循环上解析好、交给线程的
    ``install_process_factory_scope(scope.popen)`` 是同一份作用域。
    """

    loop: asyncio.AbstractEventLoop | None
    scope: Any = _NO_SCOPE


def capture_bridge() -> Bridge:
    """在事件循环上取线程桥：当前事件循环 + 当前进程作用域。"""

    from auto_mas_core.host.utils_common_process_scope import current_process_scope

    return Bridge(asyncio.get_running_loop(), current_process_scope.get())


def fallback_bridge() -> Bridge:
    """线程里没有现成的线程桥时：插件启用时记下的事件循环，不动作用域。"""

    return Bridge(service_slot.loop())


async def _in_scope(scope: Any, factory: Callable[[], Awaitable[Any]]) -> Any:
    if scope is _NO_SCOPE:
        return await factory()
    from auto_mas_core.host.utils_common_process_scope import current_process_scope

    token = current_process_scope.set(scope)
    try:
        return await factory()
    finally:
        current_process_scope.reset(token)


def _bridged(bridge: Bridge, name: str, request: Mapping[str, Any] | None) -> Any:
    loop = bridge.loop
    if loop is None or loop.is_closed():
        raise ServiceUnavailable(name, "no_loop")
    resolver = _resolver()
    return run_coroutine_from_thread(
        loop,
        _in_scope(bridge.scope, lambda: call_service(resolver, name, request)),
    )


def call_threadsafe(
    bridge: Bridge, op: str, request: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """工作线程里调一个短操作（:func:`call` 的线程版）。"""

    name = _name(op)
    try:
        value = _bridged(bridge, name, request)
    except ServiceUnavailable as exc:
        return service_unavailable_result(exc, UNAVAILABLE_MESSAGE)
    return dict(value) if isinstance(value, Mapping) else {"ok": True, "value": value}


def _seq(event: Mapping[str, Any]) -> int:
    try:
        return int(event.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def run_job_threadsafe(
    bridge: Bridge,
    family: str,
    request: Mapping[str, Any] | None = None,
    *,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    cancel_event: threading.Event | None = None,
    poll_wait: float = THREAD_POLL_WAIT_SECONDS,
) -> dict[str, Any]:
    """工作线程里跑一个长操作到结束，返回终态结果（或 ``_start`` 的失败、服务不可用）。

    事件按 ``seq`` 在本线程里交给 ``on_event``，先交事件再看 ``done``。``cancel_event`` 置位后发一次
    ``_stop``（有 ``_stop`` 的族），然后照常轮询到结束：提供方 ``_stop`` 之后有限时间内到 ``done``。
    """

    try:
        started = _bridged(bridge, _name(f"{family}_start"), request)
        if not isinstance(started, Mapping):
            return {"ok": False, "code": "invalid_reply", "message": "", "detail": {}}
        handle = started.get("handle")
        if not started.get("ok") or not isinstance(handle, str) or not handle:
            return dict(started)
        cursor = 0
        last = 0
        stop_sent = False
        while True:
            if (
                cancel_event is not None
                and cancel_event.is_set()
                and not stop_sent
                and family in _STOPPABLE
            ):
                stop_sent = True
                _bridged(bridge, _name(f"{family}_stop"), {"handle": handle})
            reply = _bridged(
                bridge,
                _name(f"{family}_poll"),
                {"handle": handle, "cursor": cursor, "wait": poll_wait},
            )
            if not isinstance(reply, Mapping) or not reply.get("ok"):
                return dict(reply) if isinstance(reply, Mapping) else {"ok": False}
            events = [e for e in reply.get("events") or [] if isinstance(e, Mapping)]
            for event in sorted(events, key=_seq):
                seq = _seq(event)
                if seq <= last:
                    continue
                last = seq
                if on_event is not None:
                    on_event(dict(event))
            try:
                cursor = max(cursor, int(reply.get("cursor", last)), last)
            except (TypeError, ValueError):
                cursor = max(cursor, last)
            if reply.get("done"):
                result = reply.get("result")
                with contextlib.suppress(ServiceUnavailable):
                    _bridged(bridge, _name(f"{family}_close"), {"handle": handle})
                return dict(result) if isinstance(result, Mapping) else {"ok": False}
    except ServiceUnavailable as exc:
        return service_unavailable_result(exc, UNAVAILABLE_MESSAGE)


def log_events(
    send_log: Callable[[str], None] | None,
) -> Callable[[dict[str, Any]], None]:
    """只把 ``log`` 事件交给 ``send_log``（逐行），别的事件忽略。"""

    def deliver(event: dict[str, Any]) -> None:
        if send_log is not None and event.get("type") == "log":
            send_log(str(event.get("message", "")))

    return deliver


__all__ = [
    "AGENT_ENV",
    "REQUIRED_OPERATIONS",
    "REQUIRES",
    "THREAD_POLL_WAIT_SECONDS",
    "UNAVAILABLE_MESSAGE",
    "AgentEnvServiceError",
    "Bridge",
    "call",
    "call_threadsafe",
    "capture_bridge",
    "failure_error",
    "fallback_bridge",
    "log_events",
    "raise_for_failure",
    "run_job",
    "run_job_threadsafe",
]
