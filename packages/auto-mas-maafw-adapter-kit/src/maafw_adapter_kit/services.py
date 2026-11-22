#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""三个专项调三块服务插件（运行、agent 环境、项目 / 项目更新）的那一层。

口径见 MFW 服务化实施方案 §2.2–§2.5、§3。通用部分（起止轮询、取消收尾、忙重试、线程桥）在解析库
``maafw_interface.service_calls``，这里只放专项要的那层：

- :class:`ServiceSlot`：专项包里模块级一份，插件 ``on_enable`` 绑宿主给的解析器、``on_disable`` 解；
  外壳、声明函数手里没有插件实例，从槽里取。槽里存的是宿主的解析器（注册表的实时视图），不是服务。
- :class:`ServiceClient`：每次调用都现取（忙重试的每一次尝试也现取），回 :class:`Reply`；生命周期
  钩子里用 :meth:`ServiceClient.call_once`（只试一次）；工作线程里用 :meth:`ServiceClient.call_sync`
  （同步服务）或 :meth:`ServiceClient.call_threadsafe`（异步服务，线程桥）。
- :class:`Operation`：一个长操作（``<族>_start`` → ``_poll`` → ``_close``），被取消时按族走取消规则
  （:data:`FAMILY_CANCEL_RULES`）；:meth:`Operation.stop` 是同步的停止入口，宿主同步回调里用，不等。
- :func:`event_dispatcher`：按事件 ``type`` 分派到专项原有的日志、进度点、记账回调。
- :class:`ProjectOpener` / :func:`open_project`：打开项目（项目服务的 ``open_*``）加专项在预约里的
  几步，被停时的宽限与「等工作做完再交回预约」照项目更新原来的 ``hold`` 搬来。
- :func:`release_run_reservation`：账号运行交回项目预约，照项目更新 ``project_path`` 原实现逐段搬来；
  「运行前设置确认退出」改问运行服务的 ``pretask_exit_watch_*``，核对作业交给项目服务的 ``run_release``。
- 操作名常量元组（专项拼 ``requires``）与各请求构造函数（只出 JSON 值的字典）。

不导入三块服务插件，也不导入宿主（SDK 只在用到时于函数体内取）。
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, TypeVar

from maafw_interface.service_calls import (
    CANCEL_DETACH,
    CANCEL_GRACE,
    CANCEL_HAND_OVER,
    CANCEL_WAIT_DONE,
    CODE_CANCELLED,
    CODE_SERVICE_UNAVAILABLE,
    CODE_UNKNOWN_HANDLE,
    POLL_WAIT_SECONDS,
    ServiceOperation,
    ServiceProtocolError,
    ServiceResolver,
    ServiceUnavailable,
    call_service,
    call_service_once,
    call_service_sync,
    call_service_threadsafe,
    service_unavailable_result,
)

from ._logging import get_logger
from .project_texts import describe_open_failure

logger = get_logger("MFW 服务调用")
# 账号运行交回预约时的告警沿用任务类的 logger 名（原先在项目更新 project_path 里就记在这个名下）
_run_logger = get_logger("MaaFW 插件自动代理")

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# 名字
# ---------------------------------------------------------------------------

RUNNER = "maafw.runner.v1"
AGENT_ENV = "maafw.agent_env.v1"
PROJECT = "maafw.project.v1"
PROJECT_UPDATE = "maafw.project_update.v1"


def _ops(prefix: str, *names: str) -> tuple[str, ...]:
    return tuple(f"{prefix}.{name}" for name in names)


def _family_ops(family: str, *, stop: bool = True) -> tuple[str, ...]:
    suffixes = (
        ("start", "poll", "stop", "close") if stop else ("start", "poll", "close")
    )
    return tuple(f"{family}_{suffix}" for suffix in suffixes)


# 长操作族（服务名去掉 ``_start`` 等后缀）
RUNNER_DESKTOP_LAUNCH = f"{RUNNER}.desktop_launch"
RUNNER_DESKTOP_QUIT = f"{RUNNER}.desktop_quit"
RUNNER_PRETASK = f"{RUNNER}.pretask"
RUNNER_PRETASK_KILL = f"{RUNNER}.pretask_kill"
RUNNER_PRETASK_EXIT_WATCH = f"{RUNNER}.pretask_exit_watch"
RUNNER_PLAN = f"{RUNNER}.plan"
AGENT_ENV_BORROW = f"{AGENT_ENV}.borrow"
AGENT_ENV_PREPARE = f"{AGENT_ENV}.prepare"
AGENT_ENV_TRIAL = f"{AGENT_ENV}.trial"
AGENT_ENV_RECONCILE = f"{AGENT_ENV}.reconcile"
PROJECT_OPEN = f"{PROJECT}.open"
PROJECT_CONFIRM = f"{PROJECT}.confirm"
PROJECT_FINISH = f"{PROJECT}.finish"
PROJECT_REPAIR = f"{PROJECT}.repair"
PROJECT_VIEW_ENSURE = f"{PROJECT}.view_ensure"
PROJECT_SCRIPT_CLONED = f"{PROJECT}.script_cloned"
PROJECT_SCRIPT_REMOVED = f"{PROJECT}.script_removed"
PROJECT_UPDATE_UPDATE = f"{PROJECT_UPDATE}.update"
PROJECT_UPDATE_PREFETCH = f"{PROJECT_UPDATE}.prefetch"
PROJECT_UPDATE_DISCOVER = f"{PROJECT_UPDATE}.discover"

# 一次性操作
RUNNER_ACCOUNT_OPEN = f"{RUNNER}.account_open"
RUNNER_ACCOUNT_CLOSE = f"{RUNNER}.account_close"
RUNNER_DESKTOP_CHECK = f"{RUNNER}.desktop_check"
RUNNER_DEVICE_ADB_PATH = f"{RUNNER}.device_adb_path"
RUNNER_DEVICE_ADB_CONFIG = f"{RUNNER}.device_adb_config"
RUNNER_DEVICE_WIN32_CONFIG = f"{RUNNER}.device_win32_config"
RUNNER_PRETASK_RERUN_CHECK = f"{RUNNER}.pretask_rerun_check"
AGENT_ENV_RUNTIME_ROUTE = f"{AGENT_ENV}.runtime_route"
AGENT_ENV_RUNTIME_CHECK = f"{AGENT_ENV}.runtime_check"
PROJECT_OWNER_REGISTER = f"{PROJECT}.owner_register"
PROJECT_OWNER_UNREGISTER = f"{PROJECT}.owner_unregister"
PROJECT_MANAGED_FIND = f"{PROJECT}.managed_find"
PROJECT_CONTEXT = f"{PROJECT}.project_context"
PROJECT_PEEK = f"{PROJECT}.project_peek"
PROJECT_RUN_RESERVE = f"{PROJECT}.run_reserve"
PROJECT_RUN_RELEASE = f"{PROJECT}.run_release"
PROJECT_OPEN_RELEASE = f"{PROJECT}.open_release"
PROJECT_UPDATE_PREFETCH_DISCARD = f"{PROJECT_UPDATE}.prefetch_discard"

#: agent 环境（2 个）：运行池路由、运行环境自检。
AGENT_ENV_OPS = (AGENT_ENV_RUNTIME_ROUTE, AGENT_ENV_RUNTIME_CHECK)
#: 运行（28 个，实施方案 §3.2 除 ``version`` 外全部）。
RUNNER_OPS = (
    RUNNER_ACCOUNT_OPEN,
    RUNNER_ACCOUNT_CLOSE,
    RUNNER_DESKTOP_CHECK,
    *_family_ops(RUNNER_DESKTOP_LAUNCH),
    *_family_ops(RUNNER_DESKTOP_QUIT, stop=False),
    RUNNER_DEVICE_ADB_PATH,
    RUNNER_DEVICE_ADB_CONFIG,
    RUNNER_DEVICE_WIN32_CONFIG,
    RUNNER_PRETASK_RERUN_CHECK,
    *_family_ops(RUNNER_PRETASK),
    *_family_ops(RUNNER_PRETASK_KILL, stop=False),
    *_family_ops(RUNNER_PRETASK_EXIT_WATCH, stop=False),
    *_family_ops(RUNNER_PLAN),
)
#: 项目（27 个，三个专项共有）。
PROJECT_OPS = (
    PROJECT_OWNER_REGISTER,
    PROJECT_OWNER_UNREGISTER,
    PROJECT_CONTEXT,
    PROJECT_RUN_RESERVE,
    PROJECT_RUN_RELEASE,
    *_family_ops(PROJECT_OPEN),
    PROJECT_OPEN_RELEASE,
    *_family_ops(PROJECT_CONFIRM),
    *_family_ops(PROJECT_FINISH, stop=False),
    *_family_ops(PROJECT_REPAIR),
    *_family_ops(PROJECT_SCRIPT_CLONED, stop=False),
    *_family_ops(PROJECT_SCRIPT_REMOVED, stop=False),
)
#: 项目更新（13 个）。
PROJECT_UPDATE_OPS = (
    *_family_ops(PROJECT_UPDATE_UPDATE),
    *_family_ops(PROJECT_UPDATE_PREFETCH),
    PROJECT_UPDATE_PREFETCH_DISCARD,
    *_family_ops(PROJECT_UPDATE_DISCOVER),
)
#: 只有 M9A 外壳要的：看项目此刻是不是正在更新。
PROJECT_PEEK_OPS = (PROJECT_PEEK,)
#: 只有通用 MFW 外壳导入要的：认托管、补视图。
SHELL_IMPORT_OPS = (PROJECT_MANAGED_FIND, *_family_ops(PROJECT_VIEW_ENSURE, stop=False))
#: 三个专项共有的 ``requires``（70 个）；M9A 再并 :data:`PROJECT_PEEK_OPS`，通用 MFW 再并
#: :data:`SHELL_IMPORT_OPS`。
ADAPTER_REQUIRES = (*AGENT_ENV_OPS, *RUNNER_OPS, *PROJECT_OPS, *PROJECT_UPDATE_OPS)

#: 各长操作族被取消时走哪条取消规则（实施方案 §3.0）。
FAMILY_CANCEL_RULES: dict[str, str] = {
    RUNNER_DESKTOP_LAUNCH: CANCEL_WAIT_DONE,
    RUNNER_PRETASK: CANCEL_WAIT_DONE,
    RUNNER_PLAN: CANCEL_WAIT_DONE,
    RUNNER_DESKTOP_QUIT: CANCEL_DETACH,
    RUNNER_PRETASK_KILL: CANCEL_DETACH,
    RUNNER_PRETASK_EXIT_WATCH: CANCEL_DETACH,
    AGENT_ENV_BORROW: CANCEL_GRACE,
    AGENT_ENV_PREPARE: CANCEL_GRACE,
    AGENT_ENV_TRIAL: CANCEL_WAIT_DONE,
    AGENT_ENV_RECONCILE: CANCEL_DETACH,
    PROJECT_OPEN: CANCEL_GRACE,
    PROJECT_CONFIRM: CANCEL_GRACE,
    PROJECT_REPAIR: CANCEL_HAND_OVER,
    PROJECT_FINISH: CANCEL_DETACH,
    PROJECT_VIEW_ENSURE: CANCEL_DETACH,
    PROJECT_SCRIPT_CLONED: CANCEL_DETACH,
    PROJECT_SCRIPT_REMOVED: CANCEL_DETACH,
    PROJECT_UPDATE_UPDATE: CANCEL_GRACE,
    PROJECT_UPDATE_PREFETCH: CANCEL_GRACE,
    PROJECT_UPDATE_DISCOVER: CANCEL_GRACE,
}
#: ``_stop`` 认 ``reason``（``cancelled`` / ``stop_requested``）的族。
STOP_REASON_FAMILIES = frozenset({PROJECT_OPEN, PROJECT_CONFIRM, PROJECT_UPDATE_UPDATE})
#: 开始前用户已停时请求里带 ``stop_requested=true`` 的族。
STOP_REQUESTED_FAMILIES = frozenset({PROJECT_CONFIRM, PROJECT_UPDATE_UPDATE})
STOP_REASON_CANCELLED = "cancelled"
STOP_REASON_STOP_REQUESTED = "stop_requested"

#: 运行服务的失败 code（判定按它们分支，``run_verdict``）。
CODE_RUN_TIMEOUT = "run_timeout"
CODE_PRETASK_FAILED = "pretask_failed"
CODE_TASK_DEADLINE_EXPIRED = "task_deadline_expired"
CODE_RUN_FAILED = "run_failed"

#: 槽还没绑（插件没启用或已停用）时 :class:`ServiceUnavailable` 的 ``reason``。
REASON_UNBOUND = "unbound"

#: 提供方重载 / 停用后句柄失效、服务拿不到时的固定话（实施方案 §1 第 12 条）。
UNKNOWN_HANDLE_MESSAGES: dict[str, str] = {
    RUNNER: "MFW 运行插件已重新加载或停用，本次运行的结果拿不到了",
    AGENT_ENV: "MFW agent 环境插件已重新加载或停用，本次环境准备的结果拿不到了",
    PROJECT: "MFW 项目插件已重新加载或停用，本次项目操作的结果拿不到了",
}

# 抄自项目更新（积木仓 AST 测试钉住两边相等）：
#: 打开项目时用户停止后，等专项那段工作收尾的上限（``project_session._ENV_PREPARE_CANCEL_GRACE_SECONDS``）。
ENV_PREPARE_CANCEL_GRACE_SECONDS = 2.0
#: 账号运行交回预约时等核对 / 清理收尾的上限（``project_path.RELEASE_CHECK_CANCEL_GRACE_SECONDS``）。
RELEASE_CHECK_CANCEL_GRACE_SECONDS = 30.0


def cancel_rule_for(family: str) -> str:
    """长操作族的取消规则；不在表里的族按 :data:`CANCEL_DETACH`（被取消即脱手）。"""

    return FAMILY_CANCEL_RULES.get(family, CANCEL_DETACH)


def unavailable_message(name: str) -> str:
    """服务名所属那块的固定话（``unknown_handle`` / ``service_unavailable`` 用同一句）。

    项目与项目更新是同一个插件，用项目那句。
    """

    if name.startswith(RUNNER + ".") or name == RUNNER:
        return UNKNOWN_HANDLE_MESSAGES[RUNNER]
    if name.startswith(AGENT_ENV + ".") or name == AGENT_ENV:
        return UNKNOWN_HANDLE_MESSAGES[AGENT_ENV]
    return UNKNOWN_HANDLE_MESSAGES[PROJECT]


# ---------------------------------------------------------------------------
# 结果与异常
# ---------------------------------------------------------------------------


class ServiceError(Exception):
    """共用库自己的服务调用异常的基类（:class:`ServiceFailure`）。

    拿不到服务是解析库的 :class:`ServiceUnavailable`、回包形状不对是 :class:`ServiceProtocolError`，
    这里原样再导出，不另起一套。
    """


class ServiceFailure(ServiceError):
    """服务回了预期内的失败（``ok: false``）。``str(exc)`` 就是提供方给的 ``message``。

    专项原来让异常往上抛、文案取 ``str(exc)`` 的地方（判定、日志），换成它以后文案逐字不变；
    判定按 ``code`` 分支（:mod:`maafw_adapter_kit.run_verdict`）。
    """

    def __init__(
        self, code: str, message: str, detail: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail: dict[str, Any] = dict(detail or {})

    def __str__(self) -> str:
        return self.message


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True)
class Reply:
    """一次服务调用的结果。``data`` 是回包原样（含 ``ok``），其余是从里面取出的常用字段。

    - 成功 ``ok=True``；良性跳过 ``ok=True``、``outcome="skipped"``（:attr:`skipped`），``reason`` 是
      ``switching`` / ``updating`` / ``occupied`` 等，``message`` 是给用户的原文；
    - 失败 ``ok=False``（:attr:`failed`），``code`` / ``message`` / ``detail``。

    不认识的 ``code`` 照常当失败，不认识的字段忽略（提供方次版本加东西不打断旧专项）。
    """

    ok: bool
    data: Mapping[str, Any] = field(default_factory=dict)
    code: str | None = None
    message: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    outcome: str | None = None
    reason: str | None = None

    @classmethod
    def from_result(cls, value: Any, *, name: str = "") -> Reply:
        """回包 → :class:`Reply`；不是带布尔 ``ok`` 的字典抛 :class:`ServiceProtocolError`。"""

        if not isinstance(value, Mapping) or not isinstance(value.get("ok"), bool):
            raise ServiceProtocolError(f"服务 {name} 回的不是带布尔 ok 的字典")
        detail = value.get("detail")
        return cls(
            ok=value["ok"],
            data=dict(value),
            code=_optional_str(value.get("code")),
            message=_optional_str(value.get("message")),
            detail=dict(detail) if isinstance(detail, Mapping) else {},
            outcome=_optional_str(value.get("outcome")),
            reason=_optional_str(value.get("reason")),
        )

    @property
    def skipped(self) -> bool:
        return self.ok and self.outcome == "skipped"

    @property
    def failed(self) -> bool:
        return not self.ok

    @property
    def lost(self) -> bool:
        """提供方没了：句柄失效（``unknown_handle``）或服务拿不到（``service_unavailable``）。"""

        return self.code in (CODE_UNKNOWN_HANDLE, CODE_SERVICE_UNAVAILABLE)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def failure(self) -> ServiceFailure:
        """这份失败对应的 :class:`ServiceFailure`（``str()`` 是 ``message``）。"""

        return ServiceFailure(self.code or "", self.message or "", self.detail)

    def expect_ok(self) -> Reply:
        """失败就抛 :class:`ServiceFailure`，否则返回自己。"""

        if self.failed:
            raise self.failure()
        return self


def ensure_json(value: Any, path: str = "request") -> None:
    """请求里只能放 JSON 值（``None``、布尔、数、字符串、列表、键为字符串的字典）。

    不合格是专项自己的 bug（把 ``Path``、模型对象塞进去了），抛 ``TypeError``；文案只带位置和类型名，
    不带值（请求里有解密后的密码）。
    """

    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"服务请求 {path} 的键不是字符串（{type(key).__name__}）"
                )
            ensure_json(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            ensure_json(item, f"{path}[{index}]")
        return
    raise TypeError(f"服务请求里只能放 JSON 值：{path} 是 {type(value).__name__}")


def _request(request: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(request or {})
    ensure_json(payload)
    return payload


def _unavailable_reply(name: str, exc: ServiceUnavailable) -> Reply:
    return Reply.from_result(
        service_unavailable_result(exc, unavailable_message(name)), name=name
    )


# ---------------------------------------------------------------------------
# 取服务
# ---------------------------------------------------------------------------


class ServiceSlot:
    """专项包里模块级一份，记住宿主给插件的服务解析器（``self.services``）。

    插件 ``on_enable`` 第一步 :meth:`bind`，``on_disable`` 最后一步 :meth:`unbind`。槽本身也照解析器的
    形状提供 :meth:`require`，每次都转给此刻绑着的解析器；没绑时抛 :class:`ServiceUnavailable`
    （``reason="unbound"``），还在跑的后台收尾据此自行结束。
    """

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self._resolver: ServiceResolver | None = None

    def bind(self, resolver: ServiceResolver) -> None:
        self._resolver = resolver

    def unbind(self) -> None:
        self._resolver = None

    @property
    def bound(self) -> bool:
        return self._resolver is not None

    def resolver(self) -> ServiceResolver:
        """此刻绑着的解析器；工作线程要用时在起线程前于事件循环上取好交进去。"""

        resolver = self._resolver
        if resolver is None:
            raise ServiceUnavailable(self.plugin_id, REASON_UNBOUND)
        return resolver

    def require(self, name: str) -> Any:
        resolver = self._resolver
        if resolver is None:
            raise ServiceUnavailable(name, REASON_UNBOUND)
        return resolver.require(name)

    @property
    def accepting(self) -> bool:
        resolver = self._resolver
        if resolver is None:
            return True  # 没绑由 require 报 unbound
        return getattr(resolver, "accepting", True) is not False


class ServiceClient:
    """专项调服务的客户端。每次调用都现取，不缓存服务对象，也不缓存提供方的版本信息。

    ``source`` 是专项的 :class:`ServiceSlot`（通常），或一个解析器（工作线程里用 :meth:`for_thread`
    得到的那种）。``caller`` 只进后端 debug 日志。每次调用记一行 debug：服务名、耗时、``ok`` /
    ``code``；不记请求（请求里可能有解密后的密码、代理凭据）。
    """

    def __init__(
        self, source: ServiceSlot | ServiceResolver, *, caller: str = ""
    ) -> None:
        self._source = source
        self.caller = caller

    @property
    def source(self) -> ServiceSlot | ServiceResolver:
        return self._source

    def resolver(self) -> ServiceResolver:
        source = self._source
        if isinstance(source, ServiceSlot):
            return source.resolver()
        return source

    def for_thread(self) -> ServiceClient:
        """起工作线程前在事件循环上调：取好此刻的解析器，线程里每次调用、每次重试都经它现取。

        顺手把本模块的惰性 logger 在这里取好：线程里不做冷导入（几个线程并发冷导入会在导入锁上死锁）。
        """

        getattr(logger, "debug", None)
        return ServiceClient(self.resolver(), caller=self.caller)

    def _trace(self, name: str, started: float, reply: Reply) -> None:
        elapsed = time.monotonic() - started
        who = f"（{self.caller}）" if self.caller else ""
        logger.debug(
            f"服务调用 {name}{who}：{elapsed:.3f}s，"
            + ("ok" if reply.ok else f"失败 {reply.code}")
        )

    async def call(self, name: str, request: Mapping[str, Any] | None = None) -> Reply:
        """调一次服务（异步或同步方法都行）。提供方暂停准入时退避重试；拿不到服务回
        ``service_unavailable`` 的 :class:`Reply`；提供方自己的 bug（直接抛异常）原样上抛。"""

        payload = _request(request)
        started = time.monotonic()
        try:
            value = await call_service(self._source, name, payload)
        except ServiceUnavailable as exc:
            reply = _unavailable_reply(name, exc)
        else:
            reply = Reply.from_result(value, name=name)
        self._trace(name, started, reply)
        return reply

    async def call_once(
        self, name: str, request: Mapping[str, Any] | None = None
    ) -> Reply:
        """生命周期钩子（``on_enable`` / ``on_disable`` 等）里用：只试一次、不重试，``require`` 与
        调用的异常原样上抛，调用方照原来的写法记 warning。"""

        payload = _request(request)
        started = time.monotonic()
        reply = Reply.from_result(
            await call_service_once(self._source, name, payload), name=name
        )
        self._trace(name, started, reply)
        return reply

    def call_sync(self, name: str, request: Mapping[str, Any] | None = None) -> Reply:
        """工作线程里调**同步**服务（属主操作、``desktop_check``）：现取、忙时 ``time.sleep`` 退避。"""

        payload = _request(request)
        started = time.monotonic()
        try:
            value = call_service_sync(self._source, name, payload)
        except ServiceUnavailable as exc:
            reply = _unavailable_reply(name, exc)
        else:
            reply = Reply.from_result(value, name=name)
        self._trace(name, started, reply)
        return reply

    def call_threadsafe(
        self,
        loop: asyncio.AbstractEventLoop,
        name: str,
        request: Mapping[str, Any] | None = None,
    ) -> Reply:
        """工作线程里调**异步**服务：经线程桥在事件循环 ``loop``（起线程前取好）上跑 :meth:`call`。"""

        payload = _request(request)
        started = time.monotonic()
        try:
            value = call_service_threadsafe(loop, self._source, name, payload)
        except ServiceUnavailable as exc:
            reply = _unavailable_reply(name, exc)
        else:
            reply = Reply.from_result(value, name=name)
        self._trace(name, started, reply)
        return reply

    def operation(
        self,
        family: str,
        *,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
        on_start: Callable[[str], Any] | None = None,
        on_result: Callable[[dict[str, Any]], Any] | None = None,
        wait: float = POLL_WAIT_SECONDS,
        limit: int | None = None,
    ) -> Operation:
        """一个长操作（还没开始）；:meth:`Operation.run` 跑它，:meth:`Operation.stop` 同步停它。"""

        return Operation(
            self,
            family,
            on_event=on_event,
            on_start=on_start,
            on_result=on_result,
            wait=wait,
            limit=limit,
        )

    async def run(
        self,
        family: str,
        request: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> Reply:
        """跑一个长操作到底：``self.operation(family, **options).run(request)``。"""

        return await self.operation(family, **options).run(request)


# ---------------------------------------------------------------------------
# 长操作
# ---------------------------------------------------------------------------


class Operation:
    """一个长操作：``<族>_start`` → 循环 ``<族>_poll``（先按 ``seq`` 把事件交给 ``on_event``、再看
    ``done``）→ ``<族>_close``。被取消时按族的取消规则收尾后重抛 ``CancelledError``
    （:data:`FAMILY_CANCEL_RULES`，实施方案 §2.5）。

    :meth:`stop` 是同步的：宿主在同步回调里通知专项停止时调它，不 ``await``——先置本地标记；已有
    句柄就在事件循环上补发 ``_stop``；``_start`` 还在途就等它回来再补发；还没 ``_start`` 的，支持的族
    （:data:`STOP_REQUESTED_FAMILIES`）在请求里带 ``stop_requested=true``。之后照常轮询到 ``done``。
    """

    def __init__(
        self,
        client: ServiceClient,
        family: str,
        *,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
        on_start: Callable[[str], Any] | None = None,
        on_result: Callable[[dict[str, Any]], Any] | None = None,
        wait: float = POLL_WAIT_SECONDS,
        limit: int | None = None,
    ) -> None:
        self.family = family
        self.cancel_rule = cancel_rule_for(family)
        self._last_seq = 0
        self._on_event = on_event
        self._operation = ServiceOperation(
            client.source,
            family,
            cancel_rule=self.cancel_rule,
            unavailable_message=unavailable_message(family),
            on_event=self._deliver,
            on_start=on_start,
            on_result=on_result,
            wait=wait,
            limit=limit,
        )

    def _deliver(self, event: dict[str, Any]) -> None:
        self._last_seq = max(self._last_seq, _event_seq(event))
        if self._on_event is not None:
            self._on_event(event)

    @property
    def handle(self) -> str | None:
        return self._operation.handle

    @property
    def cursor(self) -> int:
        """已经交给 ``on_event`` 的最后一条事件的 ``seq``：句柄交出去以后（修复作业交给
        :func:`release_run_reservation`）接着轮询从这里起，不重复交已经写过的日志。"""

        return self._last_seq

    @property
    def stop_grace(self) -> float | None:
        return self._operation.stop_grace

    @property
    def result(self) -> dict[str, Any] | None:
        return self._operation.result

    @property
    def stop_requested(self) -> bool:
        return self._operation.stop_requested

    def stop(self, reason: str | None = None) -> None:
        """同步停止入口：只置标记、在事件循环上补发 ``_stop``，不等。重复调用只算一次。

        ``reason`` 只对 :data:`STOP_REASON_FAMILIES` 有意义，缺省 ``stop_requested``（收尾期间用户
        点了停止）；别的族不带。
        """

        if self.family in STOP_REASON_FAMILIES:
            reason = reason or STOP_REASON_STOP_REQUESTED
        else:
            reason = None
        self._operation.request_stop(reason)

    async def run(self, request: Mapping[str, Any] | None = None) -> Reply:
        payload = _request(request)
        if self.stop_requested and self.family in STOP_REQUESTED_FAMILIES:
            payload["stop_requested"] = True
        value = await self._operation.run(payload)
        return Reply.from_result(value, name=self.family)


async def run_operation(
    client: ServiceClient,
    family: str,
    request: Mapping[str, Any] | None = None,
    **options: Any,
) -> Reply:
    """:class:`Operation` 的一次性写法。"""

    return await client.run(family, request, **options)


async def follow_handle(
    client: ServiceClient,
    family: str,
    handle: str,
    *,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
    timeout: float | None = None,
    wait: float = POLL_WAIT_SECONDS,
    cursor: int = 0,
) -> Reply | None:
    """轮询一个已经开始的句柄到 ``done``，返回终态结果；``timeout`` 秒还没完返回 None。

    事件按 ``seq`` 去重后交给 ``on_event``；``cursor`` 是之前已经交过的最后一条（接手别人轮询过的
    句柄时给，见 :attr:`Operation.cursor`）。句柄失效（``unknown_handle``）或服务拿不到时返回那份
    失败。不 ``_close``——句柄交给谁收由调用方定（打开项目交 ``open_release``，修复交 ``run_release``）。
    """

    source = client.source
    deadline = None if timeout is None else time.monotonic() + timeout
    cursor = max(0, int(cursor))
    last_seq = cursor
    while True:
        poll_wait = wait
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            poll_wait = min(poll_wait, remaining)
        name = f"{family}_poll"
        try:
            value = await call_service(
                source, name, {"handle": handle, "cursor": cursor, "wait": poll_wait}
            )
        except ServiceUnavailable as exc:
            return _unavailable_reply(name, exc)
        if not isinstance(value, Mapping):
            raise ServiceProtocolError(f"{name} 回的不是字典")
        if not value.get("ok"):
            return Reply.from_result(value, name=name)
        events = [
            item for item in value.get("events") or [] if isinstance(item, Mapping)
        ]
        for event in sorted(events, key=_event_seq):
            seq = _event_seq(event)
            if seq <= last_seq:
                continue
            last_seq = seq
            if on_event is not None:
                on_event(dict(event))
        try:
            cursor = max(cursor, int(value.get("cursor", last_seq)), last_seq)
        except (TypeError, ValueError):
            cursor = max(cursor, last_seq)
        if value.get("done"):
            result = value.get("result")
            if not isinstance(result, Mapping):
                raise ServiceProtocolError(f"{name} 结束了却没有结果")
            return Reply.from_result(result, name=family)


def _event_seq(event: Mapping[str, Any]) -> int:
    try:
        return int(event.get("seq") or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 事件分派
# ---------------------------------------------------------------------------


def event_dispatcher(
    *,
    log: Callable[..., Any] | None = None,
    point: Callable[..., Any] | None = None,
    record: Callable[[Any], Any] | None = None,
    stage: Callable[[str, bool | None], Any] | None = None,
    download: Callable[[int, int | None], Any] | None = None,
    progress: Callable[[Mapping[str, Any]], Any] | None = None,
) -> Callable[[Mapping[str, Any]], None]:
    """按事件 ``type`` 分派给专项原有的回调（实施方案 §2.4 的六种）：

    - ``log`` → ``log(message, warning=bool, at=float | None)``（``at`` 交给 ``format_user_log_line``，
      轮询晚到的那一点不改账号日志的时间戳）；
    - ``point`` → ``point(stage, state=…, key=…)``；
    - ``record`` → ``record(data)``；``stage`` → ``stage(stage, ok)``；
    - ``download`` → ``download(received, total)``；``progress`` → ``progress(data)``。

    没给回调的类型、不认识的类型记一行 debug 后忽略（提供方次版本可能加新事件）。
    """

    def dispatch(event: Mapping[str, Any]) -> None:
        kind = event.get("type")
        if kind == "log" and log is not None:
            at = event.get("at")
            log(
                str(event.get("message", "")),
                warning=bool(event.get("warning")),
                at=float(at) if isinstance(at, (int, float)) else None,
            )
        elif kind == "point" and point is not None:
            point(
                event.get("stage"),
                state=event.get("state") or "entered",
                key=event.get("key") or "",
            )
        elif kind == "record" and record is not None:
            record(event.get("data"))
        elif kind == "stage" and stage is not None:
            stage(event.get("stage"), event.get("ok"))
        elif kind == "download" and download is not None:
            download(event.get("received"), event.get("total"))
        elif kind == "progress" and progress is not None:
            data = event.get("data")
            progress(data if isinstance(data, Mapping) else {})
        else:
            logger.debug(f"忽略服务事件：{kind}")

    return dispatch


# ---------------------------------------------------------------------------
# 后台小任务
# ---------------------------------------------------------------------------

_BACKGROUND: set[asyncio.Future[Any]] = set()


def _spawn(coro: Awaitable[Any]) -> asyncio.Future[Any]:
    task = asyncio.ensure_future(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_background_done)
    return task


def _background_done(task: asyncio.Future[Any]) -> None:
    _BACKGROUND.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning(f"服务调用的后台收尾失败: {exc!r}")


async def _complete(coro: Awaitable[_T]) -> tuple[_T, bool]:
    """把 ``coro`` 跑完，期间调用方的取消先记下不打断；返回 ``(结果, 是否被取消过)``。

    原来那几步是同步的（放预约、拍快照），取消到不了；换成服务调用后照这个口径：做完再把取消抛出去。
    ``coro`` 自己的异常原样上抛。
    """

    task = asyncio.ensure_future(coro)
    interrupted = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                break
            interrupted = True
        except Exception:  # noqa: BLE001 - 结果下面统一取
            break
    return task.result(), interrupted


# ---------------------------------------------------------------------------
# 打开项目
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectOpenResult:
    """一次打开项目的结局（项目服务 ``open`` 的终态）。

    - ``kind``：``opened`` / ``stopped`` / ``failed``；
    - ``reason``：``failed`` 时给用户的原句（导入失败的原文、「请设置包含 interface.json …」、
      提供方没了的那句固定话）；
    - ``lease``：``{"view_path", "interface_path", "version"}``；
    - ``record_update``：要写回的项目记录 ``{"report", "source_version", "imported_at"}``，**不论结局都要
      先写回**；
    - ``env_confirm_needed``：本轮收尾要不要确认运行环境。
    """

    kind: str
    reason: str = ""
    lease: Mapping[str, Any] | None = None
    record_update: Mapping[str, Any] | None = None
    env_confirm_needed: bool = False


def _open_result(reply: Reply) -> ProjectOpenResult:
    if reply.failed:
        record_update = reply.detail.get("record_update")
        return ProjectOpenResult(
            "failed",
            reason=reply.message or "",
            record_update=record_update if isinstance(record_update, Mapping) else None,
            env_confirm_needed=bool(reply.detail.get("env_confirm_needed")),
        )
    record_update = reply.get("record_update")
    lease = reply.get("lease")
    return ProjectOpenResult(
        "stopped" if reply.outcome == "stopped" else "opened",
        lease=lease if isinstance(lease, Mapping) else None,
        record_update=record_update if isinstance(record_update, Mapping) else None,
        env_confirm_needed=bool(reply.get("env_confirm_needed")),
    )


def _current_process_scope() -> Any:
    from auto_mas_core.host.utils_common_process_scope import current_process_scope

    return current_process_scope.get()


class ProjectOpener:
    """打开项目的四步，替掉项目更新 ``MaaFWProjectSession`` 的 ``reserve`` / ``prepare`` / ``hold`` /
    ``release``（专项的 ``_check`` 结构不变）：

    1. :meth:`reserve`：``open_start``（拿预约 + 开始补视图）；拿不到预约返回良性跳过的 :class:`Reply`；
    2. 专项建一个任务做「:meth:`prepare` + 自己在预约里的几步」（写回项目记录、补默认队列……）；
    3. :meth:`hold` 等它：被取消时置 :attr:`stopping`、发 ``open_stop``，在
       :data:`ENV_PREPARE_CANCEL_GRACE_SECONDS` 内等任务做完；等不到就把 ``open_release`` 交给任务的
       完成回调，再把取消抛出去；
    4. :meth:`release`：``open_release``（已交给完成回调时什么都不做）。
    """

    def __init__(
        self,
        client: ServiceClient,
        *,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._client = client
        self._on_event = on_event
        self._handle: str | None = None
        self._stopping = False

    @property
    def handle(self) -> str | None:
        return self._handle

    @property
    def stopping(self) -> bool:
        """打开项目期间用户停止了（:meth:`hold` 被取消）：调用方在预约里的后续步骤不再开始。"""

        return self._stopping

    async def reserve(self, request: Mapping[str, Any]) -> Reply | None:
        """``open_start``。拿到预约返回 None（之后必须 :meth:`release`）；拿不到返回那份
        :class:`Reply`：良性跳过时 ``message`` 是 ``SKIP_*`` 原文，失败时是给用户的原句。"""

        reply = await self._client.call(f"{PROJECT_OPEN}_start", request)
        handle = reply.get("handle")
        if reply.ok and not reply.skipped and isinstance(handle, str) and handle:
            self._handle = handle
            return None
        return reply

    async def prepare(self) -> ProjectOpenResult:
        """轮询 ``open`` 到结束（补视图的逐行日志交给 ``on_event``），返回结局。"""

        handle = self._handle
        if handle is None:
            return ProjectOpenResult("failed", reason=unavailable_message(PROJECT))
        reply = await follow_handle(
            self._client, PROJECT_OPEN, handle, on_event=self._on_event
        )
        assert reply is not None  # 没给 timeout
        return _open_result(reply)

    def _stop_in_background(self, reason: str) -> None:
        handle = self._handle
        if handle is None:
            return
        _spawn(
            self._client.call(
                f"{PROJECT_OPEN}_stop", {"handle": handle, "reason": reason}
            )
        )

    async def hold(self, work: asyncio.Task[_T]) -> _T:
        """持着预约等 ``work``（:meth:`prepare` 加调用方在预约里的那几步）。

        补视图、组同步都在提供方的工作线程里改视图：用户这时点停止，``await`` 会立刻抛出，线程却还在
        写。预约必须等它收完再放，否则马上重开、编辑页准备环境或手动更新都能拿到预约，同时动同一棵
        视图。被取消时置位停止标记（后面的步骤不再开始）、让提供方停下，在有限宽限内等 ``work`` 做完；
        等不到就把交回预约交给它的完成回调（:meth:`release` 那时什么都不做），再把取消抛出去。
        """

        process_scope = _current_process_scope()
        if process_scope is not None:
            process_scope.retain_worker(work)
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            self._stopping = True
            self._stop_in_background(STOP_REASON_CANCELLED)
            if process_scope is None or not process_scope.closed:
                with suppress(BaseException):
                    await asyncio.wait_for(
                        asyncio.shield(work),
                        timeout=ENV_PREPARE_CANCEL_GRACE_SECONDS,
                    )
            if not work.done() and self._handle is not None:
                handle, self._handle = self._handle, None
                work.add_done_callback(
                    functools.partial(_release_after_work, self._client, handle)
                )
            raise

    async def release(self) -> None:
        """``open_release``（已交给任务完成回调、或没拿到预约时什么都不做）。"""

        handle, self._handle = self._handle, None
        if handle is not None:
            await _release_open(self._client, handle)


async def _release_open(client: ServiceClient, handle: str) -> None:
    reply = await client.call(PROJECT_OPEN_RELEASE, {"handle": handle})
    if reply.failed:
        logger.warning(f"交回 MFW 项目预约没成功：{reply.message}")


def _release_after_work(
    client: ServiceClient, handle: str, task: asyncio.Future[Any]
) -> None:
    """停止后交出去的预约：工作收完再交回；顺手取走异常，免得报「never retrieved」。"""

    if not task.cancelled():
        task.exception()
    _spawn(_release_open(client, handle))


async def open_project(
    client: ServiceClient,
    request: Mapping[str, Any],
    *,
    inside: Callable[[ProjectOpener, ProjectOpenResult], Awaitable[str | None]],
    after: Callable[[], Awaitable[str | None]] | None = None,
    on_event: Callable[[dict[str, Any]], Any] | None = None,
) -> str | None:
    """专项运行前检查里打开项目的整段：返回 None 表示打开了，往下走；字符串是给用户的那句。

    - 拿不到预约：返回 ``open_start`` 的跳过原文（``SKIP_*``，专项照旧 ``in BENIGN_SKIPS`` 判良性跳过）；
    - ``inside(opener, 结局)``：在预约里、受 :meth:`ProjectOpener.hold` 保护的那段（写回项目记录、看
      ``opener.stopping``、记 lease、补默认队列），返回问题原句或 None；
    - ``after()``：``hold`` 之后、交回预约之前的那步（拿托管 X 锁），返回问题原句或 None；
    - 这几步抛出的异常翻成 ``describe_open_failure`` 的那句；最后总是交回预约。
    """

    opener = ProjectOpener(client, on_event=on_event)
    skipped = await opener.reserve(request)
    if skipped is not None:
        return skipped.message or ""
    script_id = str(request.get("script_id") or "")

    async def work() -> str | None:
        return await inside(opener, await opener.prepare())

    task = asyncio.create_task(work())
    try:
        if problem := await opener.hold(task):
            return problem
        if after is not None:
            return await after()
        return None
    except Exception as exc:  # noqa: BLE001 - OSError 之类也要给用户一句话
        return describe_open_failure(script_id, exc)
    finally:
        await opener.release()


# ---------------------------------------------------------------------------
# 账号运行交回项目预约
# ---------------------------------------------------------------------------


async def _start_exit_watch(client: ServiceClient, account: str | None) -> str | None:
    """此刻拍运行前设置的退出快照（``pretask_exit_watch_start``），返回句柄；拿不到返回 None。"""

    reply = await client.call(
        f"{RUNNER_PRETASK_EXIT_WATCH}_start", {"account": account}
    )
    handle = reply.get("handle")
    if reply.ok and isinstance(handle, str) and handle:
        return handle
    logger.warning(f"运行前设置退出确认没开起来：{reply.message or reply.code}")
    return None


async def _exit_confirmed(client: ServiceClient, handle: str) -> bool:
    """等运行前设置的进程确认退出；没确认（清理出错、句柄失效、服务拿不到）都是 False。"""

    try:
        reply = await follow_handle(client, RUNNER_PRETASK_EXIT_WATCH, handle)
    finally:
        await client.call(f"{RUNNER_PRETASK_EXIT_WATCH}_close", {"handle": handle})
    return bool(reply is not None and reply.ok and reply.get("confirmed"))


async def _run_release(
    client: ServiceClient, key: str, *, after_job: str | None, on_job_error: str
) -> None:
    request: dict[str, Any] = {"key": key, "on_job_error": on_job_error}
    if after_job is not None:
        request["after_job"] = after_job
    reply = await client.call(PROJECT_RUN_RELEASE, request)
    if reply.failed:
        _run_logger.warning(f"MaaFW 项目预约没能交回，保留占用: {reply.message}")


async def release_run_reservation(
    client: ServiceClient,
    key: str,
    *,
    scope: Any,
    account: str | None,
    repair: Operation | str | None = None,
    on_repair_event: Callable[[dict[str, Any]], Any] | None = None,
    grace: float = RELEASE_CHECK_CANCEL_GRACE_SECONDS,
) -> None:
    """账号运行结束时交回它的项目预约（``key`` 是 ``run_reserve`` 给的键）。

    照项目更新 ``project_path.release_run_reservation`` 原实现逐段搬来。调用方先把自己记的键置空再调
    （同一份预约只放一次）。``scope`` 是此刻的进程作用域（``current_process_scope.get()``）；``account``
    是运行服务的账号句柄（没开过为 None：那时没跑过运行前设置，不用等）；``repair`` 是资源包失败后还在
    跑的修复作业（被取消时交出来、没 ``_close`` 的那个 :class:`Operation`，或它的句柄），交给
    ``run_release(after_job=…)`` 由项目服务等它；等的期间它还发的日志交给 ``on_repair_event``。

    - **作用域已请求停止**：此刻拍一次运行前设置的退出快照（``pretask_exit_watch_start``），把「等作用域
      收尾 → 清理没失败 → 运行前设置的进程确认退出 → 交回（修复作业做完再放）」交给作用域保留的后台
      任务，都确认了才放；统一进程清理失败、运行前设置没确认退出、修复出错时保留占用。
    - **否则**：修复作业还在改视图（用户停止时）就最多等 ``grace`` 秒，然后交回；没做完的由项目服务
      挂到它的完成上再放，预约不能先放。

    账号句柄的 ``account_close`` 可以在这之后照常调：退出快照在这次调用里已经拍好。
    """

    repair_cursor = 0
    if isinstance(repair, Operation):
        repair_cursor = repair.cursor
        repair = repair.handle
    if scope is not None and scope.requested:
        # #1871 的新收尾确认可能早于统一进程清理结束，不能此时
        # 放开预约；后面的强杀若失败，还可能有旧 pretask 在写目录。
        # 此刻要等的运行前设置清理与正在结束的 pretask 进程
        if account is None:
            watch, interrupted = None, False
        else:
            watch, interrupted = await _complete(_start_exit_watch(client, account))
        watch_failed = account is not None and watch is None

        async def release_after_confirmed_stop() -> None:
            await scope.finished.wait()
            if scope.cleanup_failed:
                _run_logger.error(
                    "MaaFW 任务进程未确认停止，保留项目占用，拒绝并发修改"
                )
                if watch is not None:
                    await client.call(
                        f"{RUNNER_PRETASK_EXIT_WATCH}_close", {"handle": watch}
                    )
                return
            # 清理没确认时运行服务记一句，这里保留占用
            if watch_failed:
                return
            if watch is not None and not await _exit_confirmed(client, watch):
                return
            await _run_release(client, key, after_job=repair, on_job_error="keep")

        from auto_mas_core.host.utils_common_process_scope import (
            detached_process_context,
        )

        worker = asyncio.create_task(
            release_after_confirmed_stop(),
            name="maafw-confirmed-project-release",
            context=detached_process_context(),
        )
        scope.retain_worker(worker)
        if interrupted:
            raise asyncio.CancelledError
        return

    if repair is not None:
        # 资源加载失败后的核对 / 清理还在工作线程里改视图（用户停止时）：等它收尾，等不到就
        # 由项目服务把释放挂到它的完成上，预约不能先放。
        with suppress(BaseException):
            await follow_handle(
                client,
                PROJECT_REPAIR,
                repair,
                on_event=on_repair_event,
                timeout=grace,
                cursor=repair_cursor,
            )
    _, interrupted = await _complete(
        _run_release(client, key, after_job=repair, on_job_error="release")
    )
    if interrupted:
        raise asyncio.CancelledError


# ---------------------------------------------------------------------------
# 请求构造（只出 JSON 值的字典；字段见实施方案 §3 与三份契约分稿）
# ---------------------------------------------------------------------------


def _json(value: Any) -> Any:
    """转成 JSON 值：模型 ``model_dump(mode="json")``、路径出字符串、元组 / 集合出列表、时刻出 ISO。"""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if hasattr(value, "__fspath__"):
        return str(value.__fspath__())
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return value


def _alias_dump(model: Any) -> Any:
    """解析库模型按别名出字典（控制器、agent 声明）；``None`` 原样。"""

    if model is None:
        return None
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return dump(mode="json", by_alias=True)
    return _json(model)


def _optional(**fields: Any) -> dict[str, Any]:
    """只放不是 ``None`` 的可选字段（提供方缺省等于旧行为）。"""

    return {key: _json(value) for key, value in fields.items() if value is not None}


# ---- 运行 ------------------------------------------------------------------


def account_open_request(
    owner: str, label: str, run_started_at: float
) -> dict[str, Any]:
    return {
        "owner": str(owner),
        "label": str(label),
        "run_started_at": float(run_started_at),
    }


def account_request(account: str) -> dict[str, Any]:
    """只带账号句柄的请求：``account_close``、``pretask_kill_start``、``pretask_exit_watch_start``。"""

    return {"account": account}


def desktop_spec(
    *,
    launch_mode: str,
    game_path: Any,
    launcher_path: Any,
    url: str,
    arguments: Any,
    wait_seconds: Any,
    unity_resolution: Iterable[int] | None,
    close_mode: str,
    configured_hwnd: Any,
    game_path_error: BaseException | str | None = None,
    launcher_path_error: BaseException | str | None = None,
) -> dict[str, Any]:
    """桌面游戏的 Spec（替掉运行积木的 ``MaaFWDesktopGameSpec``，字段名不变）。

    ``*_error`` 是收尾用的那份里读路径时的异常，过边界只带 ``str(exc)``。
    """

    spec: dict[str, Any] = {
        "launch_mode": str(launch_mode),
        "game_path": _json(game_path) or None,
        "launcher_path": _json(launcher_path) or None,
        "url": str(url or ""),
        "arguments": _json(arguments),
        "wait_seconds": _json(wait_seconds),
        "unity_resolution": (
            None if unity_resolution is None else [int(v) for v in unity_resolution]
        ),
        "close_mode": str(close_mode),
        "configured_hwnd": _json(configured_hwnd),
    }
    if game_path_error is not None:
        spec["game_path_error"] = str(game_path_error)
    if launcher_path_error is not None:
        spec["launcher_path_error"] = str(launcher_path_error)
    return spec


def desktop_check_request(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"spec": dict(spec)}


def desktop_launch_request(
    account: str, spec: Mapping[str, Any], controller: Any
) -> dict[str, Any]:
    return {
        "account": account,
        "spec": dict(spec),
        "controller": _alias_dump(controller),
    }


def desktop_quit_request(
    account: str,
    spec: Mapping[str, Any],
    *,
    mode: str,
    controller: Any = None,
    controller_type: str | None = None,
    failed: bool | None = None,
) -> dict[str, Any]:
    """``mode``：``retry``（重试之间关 MAS 起的游戏）/ ``final``（最终收尾）。"""

    request = {"account": account, "spec": dict(spec), "mode": mode}
    if controller is not None:
        request["controller"] = _alias_dump(controller)
    request.update(_optional(controller_type=controller_type, failed=failed))
    return request


def device_adb_path_request(
    *,
    emulator_id: str,
    device_uid: str,
    configured_path: Any,
    device_title: str | None,
    address: str,
    host_adb_path: str | None,
    ask_toolkit: str,
) -> dict[str, Any]:
    """``ask_toolkit``：``never`` / ``if_unresolved``。"""

    return {
        "emulator_id": str(emulator_id),
        "device_uid": str(device_uid),
        "configured_path": _json(configured_path) or None,
        "device_title": device_title,
        "address": str(address),
        "host_adb_path": host_adb_path,
        "ask_toolkit": ask_toolkit,
    }


def device_adb_config_request(
    *,
    emulator_id: str,
    target_id: str,
    device_uid: str,
    address: str,
    adb_path: str | None,
    profile: Mapping[str, Any] | None,
    process_id: int | None,
    process_started_at: float | None,
    configured_screencap_methods: Any,
    configured_input_methods: Any,
) -> dict[str, Any]:
    return {
        "emulator_id": str(emulator_id),
        "target_id": str(target_id),
        "device_uid": str(device_uid),
        "address": str(address),
        "adb_path": adb_path,
        "profile": None if profile is None else _json(dict(profile)),
        "emulator_process": {
            "process_id": process_id,
            "process_started_at": process_started_at,
        },
        "configured_screencap_methods": _json(configured_screencap_methods),
        "configured_input_methods": _json(configured_input_methods),
    }


def device_win32_config_request(
    *,
    controller: Any,
    configured_hwnd: Any,
    configured_screencap_method: Any,
    configured_mouse_method: Any,
    configured_keyboard_method: Any,
) -> dict[str, Any]:
    return {
        "controller": _alias_dump(controller),
        "configured_hwnd": _json(configured_hwnd),
        "configured_screencap_method": _json(configured_screencap_method),
        "configured_mouse_method": _json(configured_mouse_method),
        "configured_keyboard_method": _json(configured_keyboard_method),
    }


def pretask_rerun_check_request(
    *,
    has_pretasks: bool,
    client_reset: bool,
    controller_type: str | None,
    interface_loaded: bool,
    controller_name: str | None,
    controller: Any,
    configured_hwnd: Any,
) -> dict[str, Any]:
    return {
        "has_pretasks": bool(has_pretasks),
        "client_reset": bool(client_reset),
        "controller_type": controller_type,
        "interface_loaded": bool(interface_loaded),
        "controller_name": controller_name,
        "controller": _alias_dump(controller),
        "configured_hwnd": _json(configured_hwnd),
    }


def pretask_request(
    *,
    account: str,
    project_path: Any,
    pretasks: Iterable[Any],
    run_time_limit_minutes: int | None,
    plan_env: Mapping[str, str] | None,
    extra_env: Mapping[str, str] | None,
    secrets: Iterable[str],
) -> dict[str, Any]:
    return {
        "account": account,
        "project_path": _json(project_path),
        "pretasks": [_json(item) for item in pretasks],
        "run_time_limit_minutes": run_time_limit_minutes,
        "plan_env": {str(k): str(v) for k, v in (plan_env or {}).items()},
        "extra_env": {str(k): str(v) for k, v in (extra_env or {}).items()},
        "secrets": [str(item) for item in secrets],
    }


def plan_request(
    *,
    account: str,
    project_path: Any,
    plan: Any,
    device_config: Any,
    runtime_pool_root: Any,
    runtime_pool_id: str,
    lease_owner: str,
    run_time_limit_minutes: int,
    attachment_root: Any,
    task_time_limit_seconds: int = 0,
    task_time_limit_overrides: Mapping[str, int] | None = None,
    task_deadlines: Mapping[str, float] | None = None,
    loop_guard: bool = False,
    run_secrets: Iterable[str] = (),
    project_log_secrets: Iterable[str] = (),
    redaction_notice: str | None = None,
    game_start_source: str = "given",
    game_started_at: float | None = None,
    game_start_disk_quiet: bool = False,
    game_wait_seconds: Any = None,
    proxy_url: str | None = None,
    agent_plans: Iterable[Any] | None = None,
    extra_env: Mapping[str, str] | None = None,
    avd_emulator_id: str | None = None,
) -> dict[str, Any]:
    """``plan_start`` 的请求。

    ``plan`` 整份 ``model_dump(mode="json")`` 过边界；它的 ``declaredAgents`` 带 ``exclude=True``，整份
    dump 时会被丢掉，所以另带 ``declared_agents``（每个 ``model_dump(mode="json", by_alias=True)``），
    提供方还原后交给借环境（实施方案 §3.2、§11 D1）。``avd_emulator_id`` 非空时带
    ``avd: {"emulator_id"}``（ModAVD），否则 ``avd`` 为 null。
    """

    declared = getattr(plan, "declaredAgents", None) or []
    return {
        "account": account,
        "project_path": _json(project_path),
        "plan": _json(plan),
        "declared_agents": [_alias_dump(agent) for agent in declared],
        "device_config": _json(device_config),
        "runtime_pool_root": _json(runtime_pool_root),
        "runtime_pool_id": str(runtime_pool_id or ""),
        "lease_owner": str(lease_owner),
        "run_time_limit_minutes": int(run_time_limit_minutes),
        "attachment_root": _json(attachment_root),
        "task_time_limit_seconds": int(task_time_limit_seconds or 0),
        "task_time_limit_overrides": {
            str(k): int(v) for k, v in (task_time_limit_overrides or {}).items()
        },
        "task_deadlines": {str(k): float(v) for k, v in (task_deadlines or {}).items()},
        "loop_guard": bool(loop_guard),
        "run_secrets": [str(item) for item in run_secrets],
        "project_log_secrets": [str(item) for item in project_log_secrets],
        "redaction_notice": redaction_notice,
        "game_start_source": game_start_source,
        "game_started_at": game_started_at,
        "game_start_disk_quiet": bool(game_start_disk_quiet),
        "game_wait_seconds": _json(game_wait_seconds),
        "proxy_url": proxy_url,
        "agent_plans": (
            None if agent_plans is None else [_json(item) for item in agent_plans]
        ),
        "extra_env": {str(k): str(v) for k, v in (extra_env or {}).items()},
        "avd": None if not avd_emulator_id else {"emulator_id": str(avd_emulator_id)},
    }


# ---- agent 环境 ------------------------------------------------------------


def runtime_check_request(project_path: Any) -> dict[str, Any]:
    return {"project_path": _json(project_path)}


# ---- 项目 / 项目更新 --------------------------------------------------------


def owner_register_request(name: str, prefix: str) -> dict[str, Any]:
    return {"name": str(name), "prefix": str(prefix)}


def owner_unregister_request(name: str) -> dict[str, Any]:
    return {"name": str(name)}


def script_request(script_id: str) -> dict[str, Any]:
    """只带托管 id 的请求：``managed_find``、``project_peek``、``run_reserve``。"""

    return {"script_id": str(script_id)}


def run_release_request(
    key: str, *, after_job: str | None = None, on_job_error: str | None = None
) -> dict[str, Any]:
    """``on_job_error``：``keep`` / ``release``（缺省 ``release``）。"""

    return {"key": key, **_optional(after_job=after_job, on_job_error=on_job_error)}


def project_context_request(
    record: Mapping[str, Any], *, with_view_import_check: bool = False
) -> dict[str, Any]:
    return {
        "record": dict(record),
        "with_view_import_check": bool(with_view_import_check),
    }


def open_request(
    *,
    script_id: str,
    owner: str,
    record: Mapping[str, Any],
    script_name: str | None = None,
) -> dict[str, Any]:
    request = {"script_id": str(script_id), "owner": str(owner), "record": dict(record)}
    request.update(_optional(script_name=script_name))
    return request


def handle_request(handle: str) -> dict[str, Any]:
    """只带句柄的请求：``open_release`` 等。"""

    return {"handle": handle}


def confirm_request(
    *,
    script_id: str,
    owner: str,
    record: Mapping[str, Any],
    phase: str,
) -> dict[str, Any]:
    """``phase``：``BeforeRun`` / ``AfterRun``。开始前已停时由 :class:`Operation` 补 ``stop_requested``。"""

    return {
        "script_id": str(script_id),
        "owner": str(owner),
        "record": dict(record),
        "phase": phase,
    }


def finish_request(
    *,
    script_id: str,
    owner: str,
    script_name: str,
    record: Mapping[str, Any],
    sync_group: bool,
    round_started_at: float,
) -> dict[str, Any]:
    return {
        "script_id": str(script_id),
        "owner": str(owner),
        "script_name": str(script_name),
        "record": dict(record),
        "sync_group": bool(sync_group),
        "round_started_at": float(round_started_at),
    }


def repair_request(
    *,
    script_id: str,
    script_name: str,
    record: Mapping[str, Any],
    kind: str,
    already_checked: bool,
) -> dict[str, Any]:
    return {
        "script_id": str(script_id),
        "script_name": str(script_name),
        "record": dict(record),
        "kind": str(kind),
        "already_checked": bool(already_checked),
    }


def view_ensure_request(script_id: str | None, fallback_path: Any) -> dict[str, Any]:
    return {
        "script_id": None if script_id is None else str(script_id),
        "fallback_path": _json(fallback_path),
    }


def script_cloned_request(
    *,
    source_id: str,
    target_id: str,
    owner: str,
    source_record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": str(source_id),
        "target_id": str(target_id),
        "owner": str(owner),
        "source_record": dict(source_record),
    }


def script_removed_request(*, script_id: str, owner: str) -> dict[str, Any]:
    return {"script_id": str(script_id), "owner": str(owner)}


def update_request(
    *,
    script_id: str,
    owner: str,
    script_name: str,
    record: Mapping[str, Any],
    phase: str,
    prefetch_paths: Any = None,
    prefetch_token: str | None = None,
) -> dict[str, Any]:
    """开始前已停时由 :class:`Operation` 补 ``stop_requested``。"""

    request = {
        "script_id": str(script_id),
        "owner": str(owner),
        "script_name": str(script_name),
        "record": dict(record),
        "phase": phase,
    }
    request.update(
        _optional(prefetch_paths=prefetch_paths, prefetch_token=prefetch_token)
    )
    return request


def project_job_request(
    *, script_id: str, owner: str, record: Mapping[str, Any]
) -> dict[str, Any]:
    """``prefetch_start``、``discover_start`` 的请求。"""

    return {"script_id": str(script_id), "owner": str(owner), "record": dict(record)}


def prefetch_discard_request(token: str) -> dict[str, Any]:
    return {"token": token}


__all__ = [
    "ADAPTER_REQUIRES",
    "AGENT_ENV",
    "AGENT_ENV_OPS",
    "CODE_CANCELLED",
    "CODE_PRETASK_FAILED",
    "CODE_RUN_FAILED",
    "CODE_RUN_TIMEOUT",
    "CODE_SERVICE_UNAVAILABLE",
    "CODE_TASK_DEADLINE_EXPIRED",
    "CODE_UNKNOWN_HANDLE",
    "ENV_PREPARE_CANCEL_GRACE_SECONDS",
    "FAMILY_CANCEL_RULES",
    "PROJECT",
    "PROJECT_OPS",
    "PROJECT_PEEK_OPS",
    "PROJECT_UPDATE",
    "PROJECT_UPDATE_OPS",
    "RELEASE_CHECK_CANCEL_GRACE_SECONDS",
    "RUNNER",
    "RUNNER_OPS",
    "SHELL_IMPORT_OPS",
    "STOP_REASON_FAMILIES",
    "STOP_REQUESTED_FAMILIES",
    "UNKNOWN_HANDLE_MESSAGES",
    "Operation",
    "ProjectOpenResult",
    "ProjectOpener",
    "Reply",
    "ServiceClient",
    "ServiceError",
    "ServiceFailure",
    "ServiceProtocolError",
    "ServiceSlot",
    "ServiceUnavailable",
    "cancel_rule_for",
    "ensure_json",
    "event_dispatcher",
    "follow_handle",
    "open_project",
    "release_run_reservation",
    "run_operation",
    "unavailable_message",
]
