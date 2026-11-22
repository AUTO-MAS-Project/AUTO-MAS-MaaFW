"""MFW 一族跨插件服务调用的通用部分：调用方的起止轮询、取消收尾、忙重试，提供方的句柄表。

口径见 MFW 服务化实施方案 §2.3–§2.5（同目录分稿与本模块冲突时以实施方案为准）：

- **现取**：每次调用、忙重试的每一次尝试都重新 ``resolver.require(name)``，不缓存服务对象——提供方
  重载后旧实例的调用门永久关闭，拿着旧方法重试永远是忙。
- **忙与不可用**：``require`` 本身抛 ``PluginBusyError``（注册表已封）或别的 ``PluginError``（没登记 /
  已注销）立即放弃（:class:`ServiceUnavailable`）；拿到方法、调用时抛 ``PluginBusyError``（提供方暂停
  准入）就 0.2 s 退避后重新 ``require`` 再试，不设固定上限，只有 10 分钟保险丝。生命周期钩子里的
  调用用 :func:`call_service_once`，只试一次、异常原样上抛。
- **长操作**：``<族>_start`` → 循环 ``<族>_poll``（先按 ``seq`` 把本批事件交给回调、再看 ``done``）→
  ``<族>_close``，见 :class:`ServiceOperation`；调用方被取消时按族走四种规则之一（``CANCEL_*``）。
- **线程**：工作线程里调异步服务用 :func:`call_service_threadsafe`（事件循环在起线程前取好），调同步
  服务用 :func:`call_service_sync`（``time.sleep`` 退避，判定与保险丝同异步版）。
- **提供方**：:class:`HandleTable` 是一张句柄表，按族生成 ``_poll/_stop/_close`` 的薄方法时共用。

只用标准库（asyncio、threading、time 等），不导入宿主与插件 SDK：``PluginBusyError`` /
``PluginError`` 按类名认（SDK 补出口之前的权宜，实施方案 §1 第 14 条）。worker 子进程也会导入
解析库，本模块不得引入别的依赖。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Protocol

logger = logging.getLogger("automas.maafw.service_calls")

#: 提供方暂停准入时两次尝试之间的退避。
BUSY_RETRY_INTERVAL_SECONDS = 0.2
#: 忙重试的保险丝：只在没带宿主「暂停排空有上限」那一路改动的宿主上才可能碰到。
BUSY_RETRY_FUSE_SECONDS = 600.0
#: 有数字宽限（``stop_grace``）的族被取消后，调用方在宽限之外再多等的余量。
STOP_GRACE_MARGIN_SECONDS = 5.0
#: ``_poll`` 的 ``wait`` 上限与调用方的缺省值。
POLL_WAIT_SECONDS = 1.0
#: ``_poll`` 一次回多少条事件：缺省与上限。
POLL_LIMIT_DEFAULT = 500
POLL_LIMIT_MAX = 2000
#: 一个句柄最多积压的未读事件；超了只丢最老的 ``log`` / ``progress``。
EVENT_BACKLOG_LIMIT = 10_000
#: 终态多久没人 ``_close`` 就在下一次 ``_start`` / ``_poll`` 时顺手删掉。
HANDLE_EXPIRE_SECONDS = 600.0

CODE_UNKNOWN_HANDLE = "unknown_handle"
CODE_SERVICE_UNAVAILABLE = "service_unavailable"
CODE_CANCELLED = "cancelled"

#: 取消规则 1：有 ``_stop``、``stop_grace`` 为 null。``_stop`` 后一直轮询到 ``done``，期间再来的取消吞掉。
CANCEL_WAIT_DONE = "wait_done"
#: 取消规则 2：有 ``_stop``、``stop_grace`` 为数字。最多等 ``stop_grace + 余量``；到时或再被取消就脱手。
CANCEL_GRACE = "grace"
#: 取消规则 3：没有 ``_stop``。被取消即 ``_close`` 脱手，提供方把清理做完。
CANCEL_DETACH = "detach"
#: 取消规则 4（项目修复）：发 ``_stop``，不 ``_close``，句柄交给调用方另行处置。
CANCEL_HAND_OVER = "hand_over"
CANCEL_RULES = frozenset(
    {CANCEL_WAIT_DONE, CANCEL_GRACE, CANCEL_DETACH, CANCEL_HAND_OVER}
)
_STOPPABLE_RULES = frozenset({CANCEL_WAIT_DONE, CANCEL_GRACE, CANCEL_HAND_OVER})

REASON_SEALED = "sealed"
REASON_NOT_REGISTERED = "not_registered"
REASON_FUSE = "fuse"

#: 积压超限时可以丢的事件类型；``download`` 未读的只留最新一条。
DROPPABLE_EVENT_TYPES = frozenset({"log", "progress"})
COALESCED_EVENT_TYPES = frozenset({"download"})

# 脱手 / 补发停止这类后台小任务：留引用，免得被回收。
_BACKGROUND: set[asyncio.Task[Any]] = set()


class ServiceResolver(Protocol):
    """宿主给插件的服务解析器（``self.services``）的最小面；专项的槽对象也照这个形状。"""

    def require(self, name: str) -> Any: ...


class ServiceUnavailable(Exception):
    """服务拿不到：注册表已封（``sealed``）、没登记或已注销（``not_registered``）、忙重试的保险丝到了
    （``fuse``）。调用方立即放弃，按 ``service_unavailable`` 收尾。"""

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"服务不可用（{reason}）: {name}")
        self.name = name
        self.reason = reason


class ServiceProtocolError(RuntimeError):
    """提供方回的东西不是约定的形状（不是字典、``done`` 了却没有 ``result``……）。"""


def _class_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


def is_plugin_busy_error(exc: BaseException) -> bool:
    """宿主的 ``PluginBusyError``：类名是它、且是 ``PluginError`` 的子类（SDK 没导出，按类名认）。"""

    names = _class_names(exc)
    return "PluginBusyError" in names and "PluginError" in names


def is_plugin_error(exc: BaseException) -> bool:
    """宿主的 ``PluginError``（含子类）。"""

    return "PluginError" in _class_names(exc)


def require_service(resolver: ServiceResolver, name: str) -> Any:
    """现取一次服务；注册表已封、服务没登记时抛 :class:`ServiceUnavailable`。

    ``resolver`` 上有 ``accepting`` 且为假时按已封处理；宿主的解析器没有这个属性，靠 ``require``
    在封口后抛 ``PluginBusyError`` 认出来（只有封口时它才这样抛）。
    """

    if getattr(resolver, "accepting", True) is False:
        raise ServiceUnavailable(name, REASON_SEALED)
    try:
        return resolver.require(name)
    except Exception as exc:
        if is_plugin_busy_error(exc):
            raise ServiceUnavailable(name, REASON_SEALED) from exc
        if is_plugin_error(exc):
            raise ServiceUnavailable(name, REASON_NOT_REGISTERED) from exc
        raise


class _BusyFuse:
    """忙重试的保险丝：从第一次撞忙算起，超过 ``fuse`` 秒还忙就放弃。"""

    def __init__(self, name: str, fuse: float, clock: Callable[[], float]) -> None:
        self._name = name
        self._fuse = fuse
        self._clock = clock
        self._deadline: float | None = None

    def check(self, exc: BaseException) -> None:
        now = self._clock()
        if self._deadline is None:
            self._deadline = now + self._fuse
        if now >= self._deadline:
            raise ServiceUnavailable(self._name, REASON_FUSE) from exc


def _payload(request: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(request or {})


async def call_service(
    resolver: ServiceResolver,
    name: str,
    request: Mapping[str, Any] | None = None,
    *,
    interval: float = BUSY_RETRY_INTERVAL_SECONDS,
    fuse: float = BUSY_RETRY_FUSE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """调一次服务（同步或异步方法都行），提供方暂停准入时退避重试，每次尝试都重新 ``require``。

    提供方方法收一个字典参数；返回值原样交回。提供方自己抛的别的异常原样上抛（那是它的 bug）。
    调用方被取消时 ``CancelledError`` 照常穿出，不再重试。
    """

    guard = _BusyFuse(name, fuse, clock)
    while True:
        method = require_service(resolver, name)
        try:
            value = method(_payload(request))
            if inspect.isawaitable(value):
                value = await value
            return value
        except Exception as exc:
            if not is_plugin_busy_error(exc):
                raise
            guard.check(exc)
            logger.debug(f"服务 {name} 暂停准入，{interval} 秒后重试")
        await asyncio.sleep(interval)


async def call_service_once(
    resolver: ServiceResolver, name: str, request: Mapping[str, Any] | None = None
) -> Any:
    """生命周期钩子里用：只试一次、不重试，``require`` 与调用的异常原样上抛（与直接调用时一样）。"""

    value = resolver.require(name)(_payload(request))
    if inspect.isawaitable(value):
        value = await value
    return value


def call_service_sync(
    resolver: ServiceResolver,
    name: str,
    request: Mapping[str, Any] | None = None,
    *,
    interval: float = BUSY_RETRY_INTERVAL_SECONDS,
    fuse: float = BUSY_RETRY_FUSE_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = time.sleep,
) -> Any:
    """在工作线程里调**同步**服务（属主操作、``desktop_check``）：判定、现取与保险丝同
    :func:`call_service`，退避用 ``time.sleep``。异步服务不能这样调（抛 ``TypeError``）。"""

    guard = _BusyFuse(name, fuse, clock)
    while True:
        method = require_service(resolver, name)
        try:
            value = method(_payload(request))
        except Exception as exc:
            if not is_plugin_busy_error(exc):
                raise
            guard.check(exc)
            logger.debug(f"服务 {name} 暂停准入，{interval} 秒后重试")
        else:
            if inspect.isawaitable(value):
                if inspect.iscoroutine(value):
                    value.close()
                raise TypeError(f"服务 {name} 是异步的，不能在线程里同步调用")
            return value
        sleep(interval)


def run_coroutine_from_thread(
    loop: asyncio.AbstractEventLoop, coro: Awaitable[Any]
) -> Any:
    """线程桥：工作线程把协程交给事件循环 ``loop`` 跑，阻塞等结果。

    ``loop`` 在起线程前于事件循环上取好。协程在 ``loop`` 上建的任务带的是本线程的上下文
    （``asyncio.to_thread`` 已把调用方的 contextvars 复制进线程），所以提供方读得到调用方设的值。
    在 ``loop`` 自己的线程里调会死锁，直接拒绝。
    """

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        if inspect.iscoroutine(coro):
            coro.close()
        raise RuntimeError("不能在事件循环线程里经线程桥等自己")
    return asyncio.run_coroutine_threadsafe(coro, loop).result()  # type: ignore[arg-type]


def call_service_threadsafe(
    loop: asyncio.AbstractEventLoop,
    resolver: ServiceResolver,
    name: str,
    request: Mapping[str, Any] | None = None,
    **options: Any,
) -> Any:
    """工作线程里调异步服务：:func:`call_service` 经线程桥在 ``loop`` 上跑。"""

    return run_coroutine_from_thread(
        loop, call_service(resolver, name, request, **options)
    )


def service_unavailable_result(exc: ServiceUnavailable, message: str) -> dict[str, Any]:
    """:class:`ServiceUnavailable` 转成结果字典；``message`` 是各块那句固定话（同 ``unknown_handle``）。"""

    return {
        "ok": False,
        "code": CODE_SERVICE_UNAVAILABLE,
        "message": message,
        "detail": {"service": exc.name, "reason": exc.reason},
    }


def exception_result(code: str, exc: BaseException) -> dict[str, Any]:
    """「提供方内部抛异常」变成的失败：``message`` 是 ``str(exc)`` 原文，``detail.exception_type`` 是类名。"""

    return {
        "ok": False,
        "code": code,
        "message": str(exc),
        "detail": {"exception_type": type(exc).__name__},
    }


def _spawn(coro: Awaitable[Any]) -> asyncio.Task[Any]:
    task = asyncio.ensure_future(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_background_done)
    return task


def _background_done(task: asyncio.Task[Any]) -> None:
    _BACKGROUND.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning(f"服务调用的后台收尾失败: {exc!r}")


def _seq_of(event: Mapping[str, Any]) -> int:
    try:
        return int(event.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


class ServiceOperation:
    """调用方跑一个长操作：``<族>_start`` → 轮询 ``<族>_poll`` → ``<族>_close``。

    - 事件按 ``seq`` 升序、去重后同步交给 ``on_event``（在事件循环线程上），先交事件再看 ``done``。
    - 正常结束返回提供方的结果字典（自带 ``ok``）；``_start`` 当场失败 / 跳过时返回 ``_start`` 的回包。
    - 拿到结果时（含被取消的收尾里）先调 ``on_result``：被取消时结果只能经它交出去。
    - 服务拿不到返回 ``service_unavailable``（文案 ``unavailable_message``）；``_poll`` 回
      ``unknown_handle`` 时原样返回那份回包，都不再 ``_close``。
    - 被取消时按 ``cancel_rule`` 收尾后重抛 ``CancelledError``：

      - :data:`CANCEL_WAIT_DONE`：``_stop`` → 一直轮询到 ``done``（事件照常交出）→ ``_close``；等的期间再来的
        取消一律吞掉，只有句柄失效、服务拿不到时才放手；
      - :data:`CANCEL_GRACE`：``_stop`` → 最多等 ``stop_grace + stop_grace_margin`` 秒；到时、或期间再被取消 →
        ``_close`` 脱手；
      - :data:`CANCEL_DETACH`：即 ``_close`` 脱手；
      - :data:`CANCEL_HAND_OVER`：发 ``_stop``，不 ``_close``（句柄经 ``on_start`` 已交给调用方）。

    - :meth:`request_stop` 是同步的停止入口（宿主同步回调里用）：已有句柄就在事件循环上补发
      ``_stop``；``_start`` 还在途就等它回来再发。之后照常轮询到 ``done``。没有 ``_stop`` 的族只记标记。
    """

    def __init__(
        self,
        resolver: ServiceResolver,
        family: str,
        *,
        cancel_rule: str,
        unavailable_message: str,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
        on_start: Callable[[str], Any] | None = None,
        on_result: Callable[[dict[str, Any]], Any] | None = None,
        wait: float = POLL_WAIT_SECONDS,
        limit: int | None = None,
        stop_grace_margin: float = STOP_GRACE_MARGIN_SECONDS,
        interval: float = BUSY_RETRY_INTERVAL_SECONDS,
        fuse: float = BUSY_RETRY_FUSE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if cancel_rule not in CANCEL_RULES:
            raise ValueError(f"未知的取消规则: {cancel_rule!r}")
        self.resolver = resolver
        self.family = family
        self.cancel_rule = cancel_rule
        self.unavailable_message = unavailable_message
        self._on_event = on_event
        self._on_start = on_start
        self._on_result = on_result
        self._wait = wait
        self._limit = limit
        self._margin = stop_grace_margin
        self._call_options: dict[str, Any] = {
            "interval": interval,
            "fuse": fuse,
            "clock": clock,
        }
        self._clock = clock
        self.handle: str | None = None
        self.stop_grace: float | None = None
        self.result: dict[str, Any] | None = None
        self._cursor = 0
        self._last_seq = 0
        self._stop_requested = False
        self._stop_reason: str | None = None
        self._stop_sent = False
        self._stop_task: asyncio.Task[Any] | None = None
        self._closed = False
        self._lost = False
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- 对外 ---------------------------------------------------------------

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def request_stop(self, reason: str | None = None) -> None:
        """同步停止入口：只置标记、在事件循环上补发 ``_stop``，不等。重复调用只算一次。"""

        if self._stop_requested:
            return
        self._stop_requested = True
        self._stop_reason = reason
        if (
            self.handle is not None
            and self._loop is not None
            and self.cancel_rule in _STOPPABLE_RULES
        ):
            self._stop_task = self._loop.create_task(self._send_stop())
            _BACKGROUND.add(self._stop_task)
            self._stop_task.add_done_callback(_background_done)

    async def run(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        start_task = asyncio.ensure_future(
            call_service(
                self.resolver,
                f"{self.family}_start",
                request,
                **self._call_options,
            )
        )
        try:
            started = await asyncio.shield(start_task)
        except asyncio.CancelledError:
            # _start 在途时被取消：等它回来（它只建作业、很快），拿到句柄就按规则收尾。
            started = await self._settle(start_task)
            if self._accept_start(started):
                await self._on_cancel()
            raise
        except ServiceUnavailable as exc:
            return service_unavailable_result(exc, self.unavailable_message)
        if not self._accept_start(started):
            return dict(started)
        try:
            if self._stop_requested and self.cancel_rule in _STOPPABLE_RULES:
                await self._send_stop()
            return await self._poll_until_done()
        except asyncio.CancelledError:
            await self._on_cancel()
            raise
        except ServiceUnavailable as exc:
            self._lost = True
            return service_unavailable_result(exc, self.unavailable_message)

    # ---- 内部 ---------------------------------------------------------------

    @staticmethod
    async def _settle(task: asyncio.Future[Any]) -> Any:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:  # noqa: BLE001 - 结果下面统一取
                break
        if task.cancelled() or task.exception() is not None:
            return None
        return task.result()

    def _accept_start(self, started: Any) -> bool:
        if started is None:
            return False
        if not isinstance(started, Mapping):
            raise ServiceProtocolError(f"{self.family}_start 回的不是字典")
        handle = started.get("handle")
        if not started.get("ok") or not isinstance(handle, str) or not handle:
            return False
        self.handle = handle
        grace = started.get("stop_grace")
        self.stop_grace = float(grace) if isinstance(grace, (int, float)) else None
        if self._on_start is not None:
            self._on_start(handle)
        return True

    async def _call(self, op: str, request: Mapping[str, Any]) -> Any:
        return await call_service(
            self.resolver, f"{self.family}_{op}", request, **self._call_options
        )

    async def _send_stop(self) -> None:
        if self._stop_sent or self.handle is None:
            return
        request: dict[str, Any] = {"handle": self.handle}
        if self._stop_reason:
            request["reason"] = self._stop_reason
        try:
            await self._call("stop", request)
        except ServiceUnavailable as exc:
            logger.debug(f"{self.family}_stop 没发出去: {exc}")
        self._stop_sent = True

    async def _poll_once(self, wait: float) -> Mapping[str, Any]:
        request: dict[str, Any] = {
            "handle": self.handle,
            "cursor": self._cursor,
            "wait": wait,
        }
        if self._limit is not None:
            request["limit"] = self._limit
        reply = await self._call("poll", request)
        if not isinstance(reply, Mapping):
            raise ServiceProtocolError(f"{self.family}_poll 回的不是字典")
        if not reply.get("ok"):
            return reply
        events = [
            event for event in reply.get("events") or [] if isinstance(event, Mapping)
        ]
        for event in sorted(events, key=_seq_of):
            seq = _seq_of(event)
            if seq <= self._last_seq:
                continue
            self._last_seq = seq
            if self._on_event is not None:
                self._on_event(dict(event))
        try:
            cursor = int(reply.get("cursor", self._last_seq))
        except (TypeError, ValueError):
            cursor = self._last_seq
        self._cursor = max(self._cursor, cursor, self._last_seq)
        dropped = reply.get("dropped") or 0
        if dropped:
            logger.warning(f"{self.family} 积压过多，提供方丢掉了 {dropped} 条事件")
        return reply

    async def _poll_until_done(
        self, deadline: float | None = None
    ) -> dict[str, Any] | None:
        """轮询到 ``done`` 并 ``_close``，返回结果；到 ``deadline`` 还没完返回 None；
        句柄失效返回那份失败回包（不再 ``_close``）。"""

        while True:
            wait = self._wait
            if deadline is not None:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return None
                wait = min(wait, remaining)
            reply = await self._poll_once(wait)
            if not reply.get("ok"):
                self._lost = True
                return dict(reply)
            if reply.get("done"):
                result = reply.get("result")
                if not isinstance(result, Mapping):
                    raise ServiceProtocolError(f"{self.family}_poll 结束了却没有结果")
                self.result = dict(result)
                if self._on_result is not None:
                    self._on_result(self.result)
                await self._close()
                return self.result

    async def _close(self) -> None:
        if self._closed or self._lost or self.handle is None:
            return
        self._closed = True
        try:
            await self._call("close", {"handle": self.handle})
        except ServiceUnavailable as exc:
            logger.debug(f"{self.family}_close 没发出去: {exc}")
        except Exception as exc:  # noqa: BLE001 - close 失败不影响结果
            logger.warning(f"{self.family}_close 失败: {exc!r}")

    async def _detach(self) -> None:
        """脱手：``_close`` 放到后台任务里做完，本处再被取消也不打断它。"""

        if self._closed or self._lost:
            return
        task = _spawn(self._close())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass

    async def _on_cancel(self) -> None:
        if self.cancel_rule == CANCEL_DETACH:
            await self._detach()
        elif self.cancel_rule == CANCEL_HAND_OVER:
            task = _spawn(self._send_stop())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
        elif self.cancel_rule == CANCEL_GRACE:
            try:
                await self._send_stop()
                grace = self.stop_grace if self.stop_grace is not None else 0.0
                result = await self._poll_until_done(
                    deadline=self._clock() + grace + self._margin
                )
                if result is None:
                    await self._detach()
            except asyncio.CancelledError:
                await self._detach()
            except ServiceUnavailable:
                self._lost = True
        else:  # CANCEL_WAIT_DONE
            while True:
                try:
                    await self._send_stop()
                    await self._poll_until_done()
                    return
                except asyncio.CancelledError:
                    continue
                except ServiceUnavailable:
                    self._lost = True
                    return


async def run_operation(
    resolver: ServiceResolver,
    family: str,
    request: Mapping[str, Any] | None = None,
    **options: Any,
) -> dict[str, Any]:
    """:class:`ServiceOperation` 的一次性写法：``ServiceOperation(resolver, family, **options).run(request)``。"""

    return await ServiceOperation(resolver, family, **options).run(request)


# ---------------------------------------------------------------------------
# 提供方：句柄表
# ---------------------------------------------------------------------------


class ServiceJob:
    """句柄表里的一个作业。作业函数拿到它，用 :meth:`emit` 发事件、看 :attr:`stop_requested`。"""

    def __init__(
        self,
        table: HandleTable,
        family: str,
        handle: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self.table = table
        self.family = family
        self.handle = handle
        self.loop = loop
        self.stop_requested = False
        self.stop_reason: str | None = None
        #: 给工作线程看的停止标记（``_stop`` 时置位）。
        self.stop_event = threading.Event()
        #: 调用方 ``_close`` 时作业还没结束：作业照常跑完，结果没人要。
        self.detached = False
        self.task: asyncio.Task[Any] | None = None
        self.finished = False
        self.result: dict[str, Any] | None = None
        #: 结果已经随 ``done`` 交给调用方。
        self.result_taken = False
        self.finished_at: float | None = None
        self.last_access = table._clock()
        self._events: deque[dict[str, Any]] = deque()
        self._seq = 0
        self._dropped = 0
        self._wake = asyncio.Event()
        self._stop_handler: Callable[[str | None], Any] | None = None

    # ---- 作业侧 -------------------------------------------------------------

    def on_stop(self, handler: Callable[[str | None], Any] | None) -> None:
        """登记 ``_stop`` 时调的同步回调（收停止原因）；不登记时 ``_stop`` 取消作业任务。"""

        self._stop_handler = handler

    def emit(self, type: str, **fields: Any) -> None:
        """发一条事件（事件循环线程上调用）。``seq`` 与 ``at`` 由这里填。"""

        self._append(type, time.time(), fields)

    def emit_threadsafe(self, type: str, **fields: Any) -> None:
        """工作线程里发事件：时刻按发出那一刻取，入队在事件循环上做。"""

        self.loop.call_soon_threadsafe(
            functools.partial(self._append, type, time.time(), fields)
        )

    # ---- 表侧 ---------------------------------------------------------------

    def _append(self, type: str, at: float, fields: Mapping[str, Any]) -> None:
        self._seq += 1
        event = {**fields, "seq": self._seq, "at": at, "type": type}
        if type in COALESCED_EVENT_TYPES:
            stale = [item for item in self._events if item["type"] == type]
            for item in stale:
                self._events.remove(item)
        self._events.append(event)
        while len(self._events) > self.table.backlog_limit:
            victim = next(
                (
                    item
                    for item in self._events
                    if item["type"] in DROPPABLE_EVENT_TYPES
                ),
                None,
            )
            if victim is None:
                break
            self._events.remove(victim)
            self._dropped += 1
        self._wake.set()

    def _ack(self, cursor: int) -> None:
        while self._events and self._events[0]["seq"] <= cursor:
            self._events.popleft()

    def _pending(self, cursor: int) -> list[dict[str, Any]]:
        return [event for event in self._events if event["seq"] > cursor]

    def _request_stop(self, reason: str | None) -> None:
        first = not self.stop_requested
        self.stop_requested = True
        if first:
            self.stop_reason = reason
        self.stop_event.set()
        if self.finished:
            return
        if self._stop_handler is not None:
            try:
                self._stop_handler(reason)
            except Exception as exc:  # noqa: BLE001 - 停止回调出错不拖垮 _stop
                logger.warning(f"{self.family} 的停止回调失败: {exc!r}")
        elif self.task is not None:
            self.task.cancel()


def _clamp_wait(value: Any) -> float:
    try:
        wait = float(value)
    except (TypeError, ValueError):
        return 0.0
    if wait != wait or wait < 0:  # NaN 或负数
        return 0.0
    return min(wait, POLL_WAIT_SECONDS)


def _clamp_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return POLL_LIMIT_DEFAULT
    if limit <= 0:
        return POLL_LIMIT_DEFAULT
    return min(limit, POLL_LIMIT_MAX)


class HandleTable:
    """提供方的句柄表（放插件实例上，重载后旧句柄一律 ``unknown_handle``）。

    提供方按族生成薄方法：``<族>_start`` 里调 :meth:`start`（必须在调用方的任务里、即服务方法体内
    调，作业任务才带上调用方的 contextvars），``_poll/_stop/_close`` 直接转 :meth:`poll` /
    :meth:`stop` / :meth:`close`。作业里的异常都进结果，不从 ``_poll`` 抛。

    ``on_discard(job)`` 在终态作业离开句柄表时调（``_close``、过期清扫、脱手的作业跑完、停用清表），
    提供方据 ``job.result`` / ``job.result_taken`` 把没被取走的租约还掉。
    """

    def __init__(
        self,
        *,
        unknown_handle_message: str,
        backlog_limit: int = EVENT_BACKLOG_LIMIT,
        expire_after: float = HANDLE_EXPIRE_SECONDS,
        on_discard: Callable[[ServiceJob], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.unknown_handle_message = unknown_handle_message
        self.backlog_limit = backlog_limit
        self.expire_after = expire_after
        self._on_discard = on_discard
        self._clock = clock
        self._jobs: dict[str, ServiceJob] = {}
        self._detached: dict[str, ServiceJob] = {}

    # ---- 查询 ---------------------------------------------------------------

    def unknown_handle(self) -> dict[str, Any]:
        return {
            "ok": False,
            "code": CODE_UNKNOWN_HANDLE,
            "message": self.unknown_handle_message,
            "detail": {},
        }

    def jobs(self) -> list[ServiceJob]:
        """表里全部作业（含已脱手、还在跑的）。"""

        return [*self._jobs.values(), *self._detached.values()]

    def active(self, families: Iterable[str] | None = None) -> list[ServiceJob]:
        """没结束的作业（含已脱手的）；给 ``teardown_blockers`` 数在途作业用。"""

        wanted = None if families is None else set(families)
        return [
            job
            for job in self.jobs()
            if not job.finished and (wanted is None or job.family in wanted)
        ]

    def get(self, family: str, request: Mapping[str, Any] | None) -> ServiceJob | None:
        handle = (request or {}).get("handle")
        if not isinstance(handle, str):
            return None
        job = self._jobs.get(handle)
        if job is None or job.family != family:
            return None
        return job

    # ---- 四件套 -------------------------------------------------------------

    def start(
        self,
        family: str,
        job_fn: Callable[[ServiceJob], Awaitable[Mapping[str, Any]]],
        *,
        stop_grace: float | None = None,
        failure_code: str = "internal_error",
        cancelled_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """建作业并返回 ``{"ok": true, "handle", "stop_grace"}``。

        作业任务用 ``asyncio.create_task`` 在当前上下文里建（不传 ``context=``），读得到调用方设的
        contextvars。作业函数返回结果字典（自带 ``ok``）；抛异常时结果是 :func:`exception_result`
        （code 为 ``failure_code``）；被取消且自己没给结果时用 ``cancelled_result``。
        """

        self.sweep()
        loop = asyncio.get_running_loop()
        handle = secrets.token_hex(16)
        while handle in self._jobs or handle in self._detached:
            handle = secrets.token_hex(16)
        job = ServiceJob(self, family, handle, loop)
        self._jobs[handle] = job
        job.task = asyncio.create_task(
            self._run(job, job_fn, failure_code, cancelled_result)
        )
        return {"ok": True, "handle": handle, "stop_grace": stop_grace}

    async def _run(
        self,
        job: ServiceJob,
        job_fn: Callable[[ServiceJob], Awaitable[Mapping[str, Any]]],
        failure_code: str,
        cancelled_result: Mapping[str, Any] | None,
    ) -> None:
        try:
            value = await job_fn(job)
            if isinstance(value, Mapping) and "ok" in value:
                result = dict(value)
            else:
                result = exception_result(
                    failure_code, ServiceProtocolError("作业没有返回结果字典")
                )
        except asyncio.CancelledError:
            result = dict(
                cancelled_result
                or {"ok": False, "code": CODE_CANCELLED, "message": "", "detail": {}}
            )
        except Exception as exc:  # noqa: BLE001 - 作业里的异常都进结果
            logger.warning(f"{job.family} 作业异常: {exc!r}", exc_info=True)
            result = exception_result(failure_code, exc)
        job.result = result
        job.finished = True
        job.finished_at = self._clock()
        job._wake.set()
        if job.detached:
            self._detached.pop(job.handle, None)
            self._discard(job)

    async def poll(
        self, family: str, request: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        self.sweep()
        job = self.get(family, request)
        if job is None:
            return self.unknown_handle()
        request = request or {}
        try:
            cursor = max(0, int(request.get("cursor") or 0))
        except (TypeError, ValueError):
            cursor = 0
        wait = _clamp_wait(request.get("wait", 0))
        limit = _clamp_limit(request.get("limit"))
        job._ack(cursor)
        if not job._pending(cursor) and not job.finished and wait > 0:
            job._wake.clear()
            try:
                await asyncio.wait_for(job._wake.wait(), wait)
            except TimeoutError:
                pass
        pending = job._pending(cursor)
        events = pending[:limit]
        done = job.finished and len(events) == len(pending)
        if done:
            job.result_taken = True
        dropped, job._dropped = job._dropped, 0
        job.last_access = self._clock()
        return {
            "ok": True,
            "events": [dict(event) for event in events],
            "cursor": events[-1]["seq"] if events else cursor,
            "done": done,
            "result": dict(job.result) if done and job.result is not None else None,
            "dropped": dropped,
        }

    def stop(self, family: str, request: Mapping[str, Any] | None) -> dict[str, Any]:
        """只置停止不等；``reason`` 原样记在作业上。"""

        job = self.get(family, request)
        if job is None:
            return self.unknown_handle()
        reason = (request or {}).get("reason")
        job._request_stop(reason if isinstance(reason, str) else None)
        job.last_access = self._clock()
        return {"ok": True}

    def close(self, family: str, request: Mapping[str, Any] | None) -> dict[str, Any]:
        """终态时丢结果；没结束时脱手（不取消，作业跑完由 ``on_discard`` 收尾）。"""

        job = self.get(family, request)
        if job is None:
            return self.unknown_handle()
        del self._jobs[job.handle]
        if job.finished:
            self._discard(job)
            return {"ok": True, "detached": False}
        job.detached = True
        self._detached[job.handle] = job
        return {"ok": True, "detached": True}

    # ---- 清扫与停用 ---------------------------------------------------------

    def sweep(self) -> None:
        """终态、超过 ``expire_after`` 没被访问的句柄删掉（不起后台循环）。"""

        now = self._clock()
        expired = [
            job
            for job in self._jobs.values()
            if job.finished and now - job.last_access >= self.expire_after
        ]
        for job in expired:
            del self._jobs[job.handle]
            self._discard(job)

    def stop_all(self, reason: str | None = None) -> None:
        """对全部在途作业（含已脱手的）置停止。"""

        for job in self.active():
            job._request_stop(reason)

    async def shutdown(self, timeout: float, reason: str | None = None) -> None:
        """退出（``on_teardown``）用：置停止，在途作业最多等 ``timeout`` 秒，然后清表。"""

        self.stop_all(reason)
        tasks = [job.task for job in self.active() if job.task is not None]
        if tasks and timeout > 0:
            await asyncio.wait(tasks, timeout=timeout)
        self._clear()

    def abort_all(self, reason: str | None = None) -> None:
        """停用（``on_disable``）用：置停止、取消全部作业任务，清表。"""

        self.stop_all(reason)
        for job in self.active():
            if job.task is not None:
                job.task.cancel()
        self._clear()

    def _clear(self) -> None:
        jobs = self.jobs()
        self._jobs.clear()
        self._detached.clear()
        for job in jobs:
            if job.finished:
                self._discard(job)

    def _discard(self, job: ServiceJob) -> None:
        if self._on_discard is None:
            return
        try:
            self._on_discard(job)
        except Exception as exc:  # noqa: BLE001 - 收尾回调出错只记日志
            logger.warning(f"{job.family} 句柄收尾失败: {exc!r}")


__all__ = [
    "BUSY_RETRY_FUSE_SECONDS",
    "BUSY_RETRY_INTERVAL_SECONDS",
    "CANCEL_DETACH",
    "CANCEL_GRACE",
    "CANCEL_HAND_OVER",
    "CANCEL_RULES",
    "CANCEL_WAIT_DONE",
    "CODE_CANCELLED",
    "CODE_SERVICE_UNAVAILABLE",
    "CODE_UNKNOWN_HANDLE",
    "COALESCED_EVENT_TYPES",
    "DROPPABLE_EVENT_TYPES",
    "EVENT_BACKLOG_LIMIT",
    "HANDLE_EXPIRE_SECONDS",
    "POLL_LIMIT_DEFAULT",
    "POLL_LIMIT_MAX",
    "POLL_WAIT_SECONDS",
    "REASON_FUSE",
    "REASON_NOT_REGISTERED",
    "REASON_SEALED",
    "STOP_GRACE_MARGIN_SECONDS",
    "HandleTable",
    "ServiceJob",
    "ServiceOperation",
    "ServiceProtocolError",
    "ServiceResolver",
    "ServiceUnavailable",
    "call_service",
    "call_service_once",
    "call_service_sync",
    "call_service_threadsafe",
    "exception_result",
    "is_plugin_busy_error",
    "is_plugin_error",
    "require_service",
    "run_coroutine_from_thread",
    "run_operation",
    "service_unavailable_result",
]
