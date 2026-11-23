"""运行这一侧调 agent 环境服务（``maafw.agent_env.v1.*``）借还运行环境。

宿主侧不再直接导入 ``maafw_agent_env``（MFW 服务化实施方案 §3.2、§5）：借环境走
``borrow_start/_poll/_stop/_close``，还环境走 ``borrow_return``。服务解析器有两条来路：

- 服务操作 ``plan_start`` 把插件实例的 ``self.services`` 交给 ``MaaFWPlanRun``；
- 专项现在还直接 ``MaaFWPlanRun(request, emit)``（旧路径），这时用插件 ``on_enable`` 绑在本模块上的
  解析器（:func:`bind`）；``on_disable`` / ``on_teardown`` 时解绑。每次调用都现取服务，不缓存服务对象。

借到的结果交回 worker 前核对门面版本：运行的 ``core`` 只经 ``maafw_agent_env.core.worker_api`` 导入
agent 环境，用的是 :data:`WORKER_API_VERSION`；借环境结果的 ``worker_api`` 里没有它就不起 worker。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any

from maafw_interface.service_calls import (
    BUSY_RETRY_INTERVAL_SECONDS,
    ServiceResolver,
    ServiceUnavailable,
    call_service,
)

from ._sdk import get_logger

logger = get_logger("MaaFW 插件自动代理")

AGENT_ENV = "maafw.agent_env.v1"
BORROW = f"{AGENT_ENV}.borrow"
BORROW_RETURN = f"{AGENT_ENV}.borrow_return"
#: 本插件 ``requires`` 的 agent 环境操作（实施方案 §3.2：5 个）。
AGENT_ENV_REQUIRES: tuple[str, ...] = (
    f"{BORROW}_start",
    f"{BORROW}_poll",
    f"{BORROW}_stop",
    f"{BORROW}_close",
    BORROW_RETURN,
)

#: worker（``maafw_runner.core``）用的 agent 环境门面版本；与 ``core/runner/runner.py`` 导入的
#: ``maafw_agent_env.core.worker_api`` 那一版一致（本地测试钉住两者相等）。
WORKER_API_VERSION = 1

#: agent 环境服务拿不到、或句柄失效（agent 环境插件被重载 / 停用）时的固定话（实施方案 §1 第 12 条、§2.5）。
AGENT_ENV_UNAVAILABLE_MESSAGE = (
    "MFW agent 环境插件已重新加载或停用，本次环境准备的结果拿不到了"
)
#: 借环境结果里的门面版本对不上（实施方案 §5，新文案，只在两边版本不配套时出现）。
WORKER_API_MISMATCH_MESSAGE = (
    "MFW 运行插件与 agent 环境插件版本不配套，请把两者更新到最新版本"
)

_POLL_WAIT_SECONDS = 1.0

_bound: ServiceResolver | None = None


def bind(resolver: ServiceResolver | None) -> None:
    """插件 ``on_enable`` 时绑上宿主给的解析器（旧路径 ``MaaFWPlanRun`` 用它）。"""

    global _bound
    _bound = resolver


def unbind(resolver: ServiceResolver | None = None) -> None:
    """解绑；给了 ``resolver`` 时只在绑着的就是它时才解（重载时新实例先绑、旧实例后解）。"""

    global _bound
    if resolver is None or _bound is resolver:
        _bound = None


def bound_resolver() -> ServiceResolver | None:
    return _bound


class EnvironmentBorrow:
    """借一次运行环境：``borrow_start`` → 轮询到结束 → ``borrow_close``。

    - ``on_log``：借环境过程中的日志行（在事件循环线程上同步调）。
    - :meth:`run` 成功返回借环境结果字典（租约归调用方，用完 :func:`return_environment`）；失败抛
      ``RuntimeError``（文案是 agent 环境给的原文）。
    - :meth:`request_stop`：调用方被取消时调，发 ``borrow_stop``（``_start`` 还在途就等它回来再发），
      不等；:meth:`run` 照常轮询到结束。被停后借成的，agent 环境自己还掉。
    """

    def __init__(
        self,
        resolver: ServiceResolver,
        request: Mapping[str, Any],
        *,
        on_log: Callable[[str], Any],
    ) -> None:
        self._resolver = resolver
        self._request = dict(request)
        self._on_log = on_log
        self.handle: str | None = None
        self._cursor = 0
        self._stop_requested = False
        self._stop_sent = False
        self._closed = False

    async def run(self) -> dict[str, Any]:
        try:
            started = await call_service(
                self._resolver, f"{BORROW}_start", self._request
            )
        except ServiceUnavailable as exc:
            raise RuntimeError(AGENT_ENV_UNAVAILABLE_MESSAGE) from exc
        if not isinstance(started, Mapping) or not started.get("ok"):
            raise RuntimeError(_failure_message(started))
        self.handle = str(started.get("handle") or "")
        try:
            if self._stop_requested:
                await self._send_stop()
            result = await self._poll_until_done()
        finally:
            await self._close()
        if not result.get("ok"):
            raise RuntimeError(_failure_message(result))
        return result

    def request_stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        if self.handle:
            task = asyncio.ensure_future(self._send_stop())
            _keep(task)

    async def _send_stop(self) -> None:
        if self._stop_sent or not self.handle:
            return
        self._stop_sent = True
        with suppress(ServiceUnavailable):
            await call_service(
                self._resolver,
                f"{BORROW}_stop",
                {"handle": self.handle, "reason": "cancelled"},
            )

    async def _poll_until_done(self) -> dict[str, Any]:
        while True:
            try:
                reply = await call_service(
                    self._resolver,
                    f"{BORROW}_poll",
                    {
                        "handle": self.handle,
                        "cursor": self._cursor,
                        "wait": _POLL_WAIT_SECONDS,
                    },
                )
            except ServiceUnavailable as exc:
                self._closed = True
                raise RuntimeError(AGENT_ENV_UNAVAILABLE_MESSAGE) from exc
            if not isinstance(reply, Mapping) or not reply.get("ok"):
                # 句柄失效（agent 环境被重载 / 停用）：不再 close
                self._closed = True
                raise RuntimeError(_failure_message(reply))
            events = [e for e in reply.get("events") or [] if isinstance(e, Mapping)]
            for event in sorted(events, key=lambda item: int(item.get("seq") or 0)):
                seq = int(event.get("seq") or 0)
                if seq <= self._cursor:
                    continue
                self._cursor = seq
                if event.get("type") == "log":
                    self._on_log(str(event.get("message") or ""))
            with suppress(TypeError, ValueError):
                self._cursor = max(self._cursor, int(reply.get("cursor") or 0))
            if reply.get("done"):
                result = reply.get("result")
                if not isinstance(result, Mapping):
                    raise RuntimeError(AGENT_ENV_UNAVAILABLE_MESSAGE)
                return dict(result)

    async def _close(self) -> None:
        if self._closed or not self.handle:
            return
        self._closed = True
        try:
            await call_service(
                self._resolver, f"{BORROW}_close", {"handle": self.handle}
            )
        except Exception as exc:  # noqa: BLE001 - close 失败不影响结果
            logger.debug(f"借运行环境的句柄没能关掉: {exc!r}")


def lease_fields(result: Mapping[str, Any]) -> dict[str, Any]:
    """借环境结果里还环境要的四个标识。"""

    return {
        "runtime_pool_root": result.get("runtime_pool_root"),
        "runtime_id": result.get("runtime_id"),
        "lease_id": result.get("lease_id"),
        "binding_version": result.get("binding_version"),
    }


async def return_environment(
    resolver: ServiceResolver | None, fields: Mapping[str, Any]
) -> dict[str, Any] | None:
    """按四个标识还环境（``borrow_return``）；失败照原来的口径由调用方吞掉。"""

    if resolver is None:
        raise RuntimeError(AGENT_ENV_UNAVAILABLE_MESSAGE)
    try:
        reply = await call_service(resolver, BORROW_RETURN, dict(fields))
    except ServiceUnavailable as exc:
        raise RuntimeError(AGENT_ENV_UNAVAILABLE_MESSAGE) from exc
    if isinstance(reply, Mapping) and not reply.get("ok"):
        raise RuntimeError(_failure_message(reply))
    return dict(reply) if isinstance(reply, Mapping) else None


def worker_api_supported(result: Mapping[str, Any]) -> bool:
    """借环境结果里回报的门面版本含不含本 worker 用的那一版。"""

    versions = result.get("worker_api")
    if not isinstance(versions, (list, tuple)):
        return False
    return WORKER_API_VERSION in versions


def _failure_message(reply: Any) -> str:
    if isinstance(reply, Mapping):
        message = reply.get("message")
        if isinstance(message, str) and message:
            return message
    return AGENT_ENV_UNAVAILABLE_MESSAGE


_BACKGROUND: set[asyncio.Future[Any]] = set()


def _keep(task: asyncio.Future[Any]) -> None:
    _BACKGROUND.add(task)

    def _done(done: asyncio.Future[Any]) -> None:
        _BACKGROUND.discard(done)
        if not done.cancelled() and done.exception() is not None:
            logger.debug(f"借运行环境的停止没发出去: {done.exception()!r}")

    task.add_done_callback(_done)


__all__ = [
    "AGENT_ENV",
    "AGENT_ENV_REQUIRES",
    "AGENT_ENV_UNAVAILABLE_MESSAGE",
    "BORROW",
    "BORROW_RETURN",
    "BUSY_RETRY_INTERVAL_SECONDS",
    "WORKER_API_MISMATCH_MESSAGE",
    "WORKER_API_VERSION",
    "EnvironmentBorrow",
    "bind",
    "bound_resolver",
    "lease_fields",
    "return_environment",
    "unbind",
    "worker_api_supported",
]
