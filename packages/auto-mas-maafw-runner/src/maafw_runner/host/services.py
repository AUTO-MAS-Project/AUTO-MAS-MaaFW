"""运行的 29 个服务操作（``maafw.runner.v1.<操作>``），混进插件类。

契约见 MFW 服务化实施方案 §3.2（细节照同目录 ``契约-maafw_runner.md``）。这里只是包装：
跑计划、运行前设置、桌面游戏、设备配置都转调本包原有的 ``MaaFWPlanRun``、``MaaFWPretaskRunner``、
``MaaFWDesktopGame``、``device_config``，那些类与函数原样保留，专项照旧能直接用。

- 请求先经 ``contract.py`` 校验；多出来的键只按键名记 debug，请求本身一律不进日志（里面有解密后的
  密码与打码值）。
- 账号句柄（``account_open``）：一个账号这一轮的桌面游戏与运行前设置两个对象跨尝试保留在这里，
  它们的事件交给本账号当前在跑的那个作业；``account_close`` 总是成功，账号下还有作业时延后到最后一个
  作业结束再丢（§2.3、§11 R4）。同一账号同一族作业同时只能有一个（``account_busy``）。
- 长操作用解析库 ``service_calls.HandleTable``：作业任务在 ``*_start`` 这次调用里
  ``asyncio.create_task`` 建，读得到调用方的 ``current_process_scope``、``desktop_process_target``、
  ``current_game_session``；不能用 ``background_tasks.spawn``（它换成脱离作用域的上下文）。
- ``_stop``（``desktop_launch``、``pretask``、``plan`` 三族）取消作业任务，走原来调用方被取消时的
  同一条 ``CancelledError`` 路径；另外三族的清理不许中途放弃，不登记 ``_stop``，退出时的「置停止」也不取消它们。

本模块顶层不导入 SDK 与运行流程模块：插件类在宿主里才建，测试也能不带宿主导入它。流程模块在
服务方法体里（事件循环上）导入。
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from maafw_interface.service_calls import (
    HandleTable,
    ServiceJob,
)

from .. import contract
from ._sdk import get_logger

logger = get_logger("MaaFW 插件自动代理")

#: 提供方被重载 / 停用后旧句柄的固定话（实施方案 §1 第 12 条）。
UNKNOWN_HANDLE_MESSAGE = "MFW 运行插件已重新加载或停用，本次运行的结果拿不到了"
UNKNOWN_ACCOUNT_MESSAGE = "MFW 运行插件里找不到这个账号的运行状态（可能已重新加载）"
ACCOUNT_BUSY_MESSAGE = "这个账号还有运行插件的同类作业没结束"
CANCELLED_MESSAGE = "已停止"
#: 拒绝停用、重载、卸载（沿用原来那一句，N 数有在途作业的账号，§2.7）。
BLOCKER_RUNS = "MFW 运行积木还有 {count} 个运行没有结束，请先停止任务再操作"
#: 退出时（``on_teardown``）最多等多久：Runtime 关机只给后端约 5 秒。
TEARDOWN_WAIT_SECONDS = 2.0

#: 设备配置失败时把 ``RuntimeError`` 原文认成 code（文案照旧，调用方照抛 ``RuntimeError(message)``）。
_HWND_NOT_IN_SESSION = "配置的窗口句柄不在桌面分身内"
_WINDOW_NOT_FOUND = "未找到匹配 MaaFW Win32 controller 的窗口"


def _ignore_stop(_reason: str | None) -> None:
    """没有取消点的族：``_stop`` 不登记，退出时的「置停止」也不取消作业任务。"""


class _ClientPathUnreadable(RuntimeError):
    """收尾关游戏时读不出客户端路径（spec 里带过来的异常原文）。"""


class _EventLog:
    """短操作结果里的 ``events``：按发生顺序记，同 ``_poll`` 事件的形状。"""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, type: str, **fields: Any) -> None:
        self.events.append(
            {**fields, "seq": len(self.events) + 1, "at": time.time(), "type": type}
        )

    def log(self, message: str) -> None:
        self.emit("log", message=str(message), warning=False)

    def sink(self, event: Any) -> None:
        _forward_event(self.emit, event)


def _forward_event(emit: Callable[..., None], event: Any) -> None:
    """``plan_run`` 的四种事件对象换成服务事件（``log`` / ``point`` / ``record`` / ``stage``）。"""

    from .plan_run import (
        MaaFWPlanRunLog,
        MaaFWPlanRunPoint,
        MaaFWPlanRunRecord,
        MaaFWPlanRunStage,
    )

    if isinstance(event, MaaFWPlanRunLog):
        emit("log", message=event.message, warning=bool(event.warning))
    elif isinstance(event, MaaFWPlanRunPoint):
        emit("point", stage=event.stage, state=event.state, key=event.key)
    elif isinstance(event, MaaFWPlanRunRecord):
        emit("record", data=event.data)
    elif isinstance(event, MaaFWPlanRunStage):
        emit("stage", stage=event.stage, ok=event.ok)
    else:  # pragma: no cover - 事件出口只发这四种
        logger.debug(f"MFW 运行插件收到不认识的事件: {type(event).__name__}")


@dataclass
class _Account:
    """一个账号这一轮的运行状态（跨尝试保留）。"""

    account_id: str
    owner: str
    label: str
    desktop: Any = None
    pretasks: Any = None
    #: 族 → 没结束的作业句柄（同族同时只能有一个）。
    active: dict[str, str] = field(default_factory=dict)
    #: 没结束的作业（含已脱手的），按句柄。
    jobs: dict[str, ServiceJob] = field(default_factory=dict)
    #: 两个对象的事件此刻交给哪个作业。
    desktop_job: ServiceJob | None = None
    pretask_job: ServiceJob | None = None
    #: ``account_close`` 时还有作业：作业都结束后丢掉。
    close_deferred: bool = False

    def forward(self, which: str, event: Any) -> None:
        job = self.desktop_job if which == "desktop" else self.pretask_job
        if job is not None and not job.finished:
            _forward_event(job.emit, event)
            return
        # 没有作业在收：只记后端日志（例如脱手后收尾里的话）
        message = getattr(event, "message", None)
        if isinstance(message, str):
            logger.info(message)


def _interface_shim(controller: Any, name: str | None, loaded: bool) -> Any:
    """原函数收 ``interface`` 只为在里面按名字找控制器：给它一个只装了这一个控制器的替身。

    interface 没加载时返回 None（原来的 ``interface is None`` 分支）；加载了却没找到控制器时替身
    是空的，原函数在原来那一步报「未找到 controller: <名字>」。
    """

    if not loaded:
        return None

    class _Shim:
        pass

    shim = _Shim()
    shim.controller = [] if controller is None else [controller]  # type: ignore[attr-defined]
    return shim


def _controller_model(data: Mapping[str, Any] | None) -> Any:
    if data is None:
        return None
    from maafw_interface.interface.models import MaaFWController

    return MaaFWController.model_validate(dict(data))


def _jsonable(value: Any) -> Any:
    from pathlib import Path

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


class RunnerServices:
    """运行服务操作；插件类混进它（``plugin.py``），也可以单独构造做测试。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._handles = HandleTable(unknown_handle_message=UNKNOWN_HANDLE_MESSAGE)
        self._accounts: dict[str, _Account] = {}

    # ------------------------------------------------------------------
    # 公共小件
    # ------------------------------------------------------------------

    def _parse(self, op: str, request: Any) -> tuple[Any, dict[str, Any] | None]:
        parsed, failure, extra = contract.parse_request(op, request)
        if extra:
            logger.debug(
                f"MFW 运行插件 {op} 请求里有不认识的键，已忽略：{', '.join(extra)}"
            )
        return parsed, failure

    @staticmethod
    def _failure(code: str, message: str, **detail: Any) -> dict[str, Any]:
        return {"ok": False, "code": code, "message": message, "detail": detail}

    def _account(
        self, account_id: Any, *, allow_closing: bool = False
    ) -> _Account | None:
        account = (
            self._accounts.get(account_id) if isinstance(account_id, str) else None
        )
        if account is None or (account.close_deferred and not allow_closing):
            return None
        return account

    def _unknown_account(self) -> dict[str, Any]:
        return self._failure("unknown_account", UNKNOWN_ACCOUNT_MESSAGE)

    def _start_account_job(
        self,
        account: _Account,
        family: str,
        body: Callable[[ServiceJob], Any],
        *,
        stoppable: bool,
    ) -> dict[str, Any]:
        """在账号下建一个作业；同族已有一个没结束时 ``account_busy``。"""

        if family in account.active:
            return self._failure("account_busy", ACCOUNT_BUSY_MESSAGE, family=family)

        async def run(job: ServiceJob) -> Any:
            if not stoppable:
                job.on_stop(_ignore_stop)
            try:
                return await body(job)
            finally:
                self._job_finished(account, family, job)

        started = self._handles.start(
            family,
            run,
            stop_grace=None,
            failure_code="run_failed",
            cancelled_result=self._failure("cancelled", CANCELLED_MESSAGE),
        )
        handle = started["handle"]
        job = self._handles.get(family, {"handle": handle})
        account.active[family] = handle
        if job is not None:
            account.jobs[handle] = job
        return started

    def _job_finished(self, account: _Account, family: str, job: ServiceJob) -> None:
        if account.active.get(family) == job.handle:
            del account.active[family]
        account.jobs.pop(job.handle, None)
        if account.desktop_job is job:
            account.desktop_job = None
        if account.pretask_job is job:
            account.pretask_job = None
        if account.close_deferred and not account.jobs:
            self._drop_account(account)

    def _drop_account(self, account: _Account) -> None:
        if self._accounts.get(account.account_id) is account:
            del self._accounts[account.account_id]

    def _poll(self, family: str, request: Any) -> Any:
        _, failure = self._parse(f"{family}_poll", request)
        if failure is not None:
            return _done(failure)
        return self._handles.poll(family, request)

    def _stop(self, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(f"{family}_stop", request)
        if failure is not None:
            return failure
        return self._handles.stop(family, request)

    def _close(self, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(f"{family}_close", request)
        if failure is not None:
            return failure
        return self._handles.close(family, request)

    @staticmethod
    def _desktop_spec(spec: Any) -> Any:
        from pathlib import Path

        from .desktop_game import MaaFWDesktopGameSpec

        def path(value: str | None) -> Path | None:
            return Path(value) if value else None

        def error(value: str | None) -> Exception | None:
            return None if value is None else _ClientPathUnreadable(value)

        resolution = spec.unity_resolution
        return MaaFWDesktopGameSpec(
            launch_mode=spec.launch_mode,
            game_path=path(spec.game_path),
            launcher_path=path(spec.launcher_path),
            url=spec.url,
            arguments=spec.arguments,
            wait_seconds=spec.wait_seconds,
            unity_resolution=None if resolution is None else tuple(resolution),
            close_mode=spec.close_mode,
            configured_hwnd=spec.configured_hwnd,
            game_path_error=error(spec.game_path_error),
            launcher_path_error=error(spec.launcher_path_error),
        )

    @staticmethod
    def _desktop_state(account: _Account) -> dict[str, Any]:
        desktop = account.desktop
        return {"opened": bool(desktop.opened), "started_at": desktop.started_at}

    @staticmethod
    async def _emulator(emulator_id: str) -> Any:
        """在这次调用里取模拟器入口（同专项：``GameManager.get_emulator_instance``，取不到当没有）。"""

        if not emulator_id or emulator_id.strip() in ("", "-"):
            return None
        try:
            from auto_mas_core.host.core import GameManager

            return await GameManager.get_emulator_instance(emulator_id)
        except Exception as exc:  # noqa: BLE001 - 缺模拟器按没有继续，同专项
            logger.debug(f"MFW 运行插件取模拟器实例失败，按无模拟器继续：{exc}")
            return None

    @staticmethod
    def _process_scope() -> Any:
        from auto_mas_core.host.utils_common_process_scope import current_process_scope

        return current_process_scope.get()

    @staticmethod
    def _desktop_target() -> Any:
        from auto_mas_core.host.utils_common_process_session import (
            desktop_process_target,
        )

        return desktop_process_target.get()

    # ------------------------------------------------------------------
    # 普通操作
    # ------------------------------------------------------------------

    async def version(self, request: Any = None) -> dict[str, Any]:
        _, failure = self._parse("version", request)
        if failure is not None:
            return failure
        from ..plugin import PACKAGE_NAME, PACKAGE_VERSION

        return {"ok": True, "package": PACKAGE_NAME, "version": PACKAGE_VERSION}

    async def account_open(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("account_open", request)
        if failure is not None:
            return failure
        from .desktop_game import MaaFWDesktopGame
        from .pretask_run import MaaFWPretaskRunner

        account_id = secrets.token_hex(16)
        while account_id in self._accounts:
            account_id = secrets.token_hex(16)
        account = _Account(account_id, parsed.owner, parsed.label)
        # 两个对象在这次调用里建（桌面游戏构造时经 SDK 取 ClientProcess）
        account.desktop = MaaFWDesktopGame(
            lambda event: account.forward("desktop", event)
        )
        account.desktop.mark_run_started(parsed.run_started_at)
        account.pretasks = MaaFWPretaskRunner(
            lambda event: account.forward("pretask", event)
        )
        self._accounts[account_id] = account
        return {"ok": True, "account": account_id}

    async def account_close(self, request: Any = None) -> dict[str, Any]:
        """总是成功：不存在当已关；账号下还有作业时延后到最后一个作业结束（§2.3、§11 R4）。"""

        parsed, failure = self._parse("account_close", request)
        if failure is not None:
            return failure
        account = self._accounts.get(parsed.account)
        if account is None:
            return {"ok": True, "deferred": False}
        if account.jobs:
            account.close_deferred = True
            return {"ok": True, "deferred": True}
        self._drop_account(account)
        return {"ok": True, "deferred": False}

    def desktop_check(self, request: Any = None) -> dict[str, Any]:
        """同步：MAS 管不管启动游戏，管的话缺什么配置（读盘，调用方在工作线程里经同步调用助手调）。"""

        parsed, failure = self._parse("desktop_check", request)
        if failure is not None:
            return failure
        from .desktop_game import describe_desktop_launch_error, desktop_launch_managed

        spec = self._desktop_spec(parsed.spec)
        managed = desktop_launch_managed(spec)
        return {
            "ok": True,
            "managed": managed,
            "error": describe_desktop_launch_error(spec) if managed else None,
        }

    async def device_adb_path(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("device_adb_path", request)
        if failure is not None:
            return failure
        from types import SimpleNamespace

        from .device_config import resolve_adb_path, resolve_login_adb_path

        events = _EventLog()
        emulator = await self._emulator(parsed.emulator_id)
        host_adb_path = parsed.host_adb_path
        if host_adb_path is None:
            # 原函数只拿 device_info 在日志里写标题
            title = parsed.device_title
            host_adb_path = await resolve_adb_path(
                emulator,
                parsed.device_uid,
                configured_path=parsed.configured_path,
                device_info=SimpleNamespace(title=title) if title is not None else None,
                log=events.log,
            )
        adb_path = await resolve_login_adb_path(
            parsed.address,
            host_adb_path,
            ask_toolkit=(
                parsed.ask_toolkit == "if_unresolved"
                and host_adb_path is None
                and bool(parsed.address)
            ),
            log=events.log,
        )
        return {
            "ok": True,
            "host_adb_path": host_adb_path,
            "adb_path": adb_path,
            "events": events.events,
        }

    async def device_adb_config(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("device_adb_config", request)
        if failure is not None:
            return failure
        from types import SimpleNamespace

        from .device_config import (
            MaaFWAdbControlProfile,
            adb_ready_timeout,
            build_adb_control_profile,
            build_adb_device_config,
        )

        events = _EventLog()
        emulator = await self._emulator(parsed.emulator_id)
        if parsed.profile is not None:
            profile = MaaFWAdbControlProfile(
                parsed.profile.emulator_type,
                parsed.profile.screencap_extra,
                parsed.profile.input_extra,
                dict(parsed.profile.config),
            )
        else:
            try:
                profile = await build_adb_control_profile(
                    emulator,
                    target_id=parsed.target_id,
                    device_uid=parsed.device_uid,
                    log=events.log,
                )
            except Exception as exc:  # noqa: BLE001 - ModAVD 构造不出 AVDExtras 配置（原文照给）
                return self._failure(
                    "avd_profile_unavailable",
                    str(exc),
                    exception_type=type(exc).__name__,
                    events=events.events,
                )
        process = parsed.emulator_process
        try:
            device_config = build_adb_device_config(
                address=parsed.address,
                adb_path=parsed.adb_path,
                profile=profile,
                device_info=SimpleNamespace(
                    process_id=process.process_id,
                    process_started_at=process.process_started_at,
                ),
                configured_screencap_methods=parsed.configured_screencap_methods,
                configured_input_methods=parsed.configured_input_methods,
                ready_timeout=adb_ready_timeout(emulator),
            )
        except Exception as exc:  # noqa: BLE001 - 配置原值不合法等（原文照给）
            return self._failure(
                "device_config_failed",
                str(exc),
                exception_type=type(exc).__name__,
                events=events.events,
            )
        return {
            "ok": True,
            "device_config": device_config.model_dump(mode="json"),
            "profile": {
                "emulator_type": profile.emulator_type,
                "screencap_extra": bool(profile.screencap_extra),
                "input_extra": bool(profile.input_extra),
                "config": _jsonable(profile.config),
            },
            "events": events.events,
        }

    async def device_win32_config(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("device_win32_config", request)
        if failure is not None:
            return failure
        from maafw_interface.controller_win32.service import (
            WIN32_NO_WINDOW_RULES_MESSAGE,
        )
        from pydantic import ValidationError

        from .device_config import build_win32_device_config, resolve_window_handle

        events = _EventLog()
        try:
            controller = _controller_model(parsed.controller)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("controller",)
            )
        try:
            hwnd = await resolve_window_handle(
                controller, parsed.configured_hwnd, log=events.log
            )
            device_config = build_win32_device_config(
                controller,
                hwnd,
                configured_screencap_method=parsed.configured_screencap_method,
                configured_mouse_method=parsed.configured_mouse_method,
                configured_keyboard_method=parsed.configured_keyboard_method,
                log=events.log,
            )
        except Exception as exc:  # noqa: BLE001 - 原文照给，调用方照抛 RuntimeError(message)
            message = str(exc)
            code = {
                _HWND_NOT_IN_SESSION: "hwnd_not_in_session",
                WIN32_NO_WINDOW_RULES_MESSAGE: "no_window_rules",
                _WINDOW_NOT_FOUND: "window_not_found",
            }.get(message, "device_config_failed")
            return self._failure(
                code, message, exception_type=type(exc).__name__, events=events.events
            )
        return {
            "ok": True,
            "device_config": device_config.model_dump(mode="json"),
            "hwnd": int(hwnd),
            "events": events.events,
        }

    async def pretask_rerun_check(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("pretask_rerun_check", request)
        if failure is not None:
            return failure
        from types import SimpleNamespace

        from pydantic import ValidationError

        from .pretask_run import pretasks_need_rerun

        try:
            controller = _controller_model(parsed.controller)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("controller",)
            )
        events = _EventLog()
        # 原函数只看计划的这三样；判定顺序、文案原样
        plan = SimpleNamespace(
            pretasks=[True] if parsed.has_pretasks else [],
            controllerType=parsed.controller_type,
            controllerName=parsed.controller_name,
        )
        try:
            rerun = await pretasks_need_rerun(
                plan,  # type: ignore[arg-type]
                _interface_shim(
                    controller, parsed.controller_name, parsed.interface_loaded
                ),
                client_reset=parsed.client_reset,
                configured_hwnd=parsed.configured_hwnd,
                emit=events.sink,
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            code = (
                "controller_not_found"
                if message.startswith("未找到 controller:")
                else "rerun_check_failed"
            )
            return self._failure(
                code, message, exception_type=type(exc).__name__, events=events.events
            )
        return {"ok": True, "rerun": bool(rerun), "events": events.events}

    # ------------------------------------------------------------------
    # 桌面游戏
    # ------------------------------------------------------------------

    async def desktop_launch_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("desktop_launch_start", request)
        if failure is not None:
            return failure
        account = self._account(parsed.account)
        if account is None:
            return self._unknown_account()
        from pydantic import ValidationError

        try:
            controller = _controller_model(parsed.controller)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("controller",)
            )
        spec = self._desktop_spec(parsed.spec)
        loaded = (
            parsed.interface_loaded
            if parsed.interface_loaded is not None
            else controller is not None
        )
        name = parsed.controller_name or (controller.name if controller else None)
        interface = _interface_shim(controller, name, loaded)
        desktop = self._desktop_target()

        async def body(job: ServiceJob) -> dict[str, Any]:
            account.desktop_job = job
            try:
                await account.desktop.ensure_started(
                    spec, interface=interface, controller_name=name, desktop=desktop
                )
            except asyncio.CancelledError:
                return self._failure(
                    "cancelled", CANCELLED_MESSAGE, desktop=self._desktop_state(account)
                )
            except Exception as exc:  # noqa: BLE001 - 原文照给（缺 exe、等窗口超时……）
                return self._failure(
                    "desktop_launch_failed",
                    str(exc),
                    exception_type=type(exc).__name__,
                    desktop=self._desktop_state(account),
                )
            return {"ok": True, "desktop": self._desktop_state(account)}

        return self._start_account_job(account, "desktop_launch", body, stoppable=True)

    async def desktop_launch_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("desktop_launch", request)

    async def desktop_launch_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop("desktop_launch", request)

    async def desktop_launch_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("desktop_launch", request)

    async def desktop_quit_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("desktop_quit_start", request)
        if failure is not None:
            return failure
        account = self._account(parsed.account)
        if account is None:
            return self._unknown_account()
        from pydantic import ValidationError

        try:
            controller = _controller_model(parsed.controller)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("controller",)
            )
        spec = self._desktop_spec(parsed.spec)
        loaded = (
            parsed.interface_loaded
            if parsed.interface_loaded is not None
            else controller is not None
        )
        name = parsed.controller_name or (controller.name if controller else None)
        interface = _interface_shim(controller, name, loaded)
        desktop = self._desktop_target()

        async def body(job: ServiceJob) -> dict[str, Any]:
            account.desktop_job = job
            closed: bool | None = None
            try:
                if parsed.mode == "retry":
                    closed = await account.desktop.close(spec)
                else:
                    await account.desktop.close_after_run(
                        spec,
                        interface=interface,
                        controller_name=name,
                        controller_type=parsed.controller_type,
                        failed=parsed.failed,
                        desktop=desktop,
                    )
            except _ClientPathUnreadable as exc:
                return self._failure(
                    "client_path_unreadable",
                    str(exc),
                    desktop=self._desktop_state(account),
                )
            except Exception as exc:  # noqa: BLE001
                return self._failure(
                    "desktop_quit_failed",
                    str(exc),
                    exception_type=type(exc).__name__,
                    desktop=self._desktop_state(account),
                )
            return {
                "ok": True,
                "closed": closed,
                "desktop": self._desktop_state(account),
            }

        return self._start_account_job(account, "desktop_quit", body, stoppable=False)

    async def desktop_quit_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("desktop_quit", request)

    async def desktop_quit_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("desktop_quit", request)

    # ------------------------------------------------------------------
    # 运行前设置
    # ------------------------------------------------------------------

    async def pretask_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("pretask_start", request)
        if failure is not None:
            return failure
        account = self._account(parsed.account)
        if account is None:
            return self._unknown_account()
        from maafw_interface.runner.models import MaaFWPretaskRunPlan
        from pydantic import ValidationError

        from .pretask_run import MaaFWPretaskError, MaaFWPretaskRunRequest

        pretasks = []
        for index, item in enumerate(parsed.pretasks):
            try:
                pretasks.append(MaaFWPretaskRunPlan.model_validate(item))
            except ValidationError as exc:
                return contract.invalid_request(
                    contract.error_entries(exc), prefix=("pretasks", index)
                )
        run_request = MaaFWPretaskRunRequest(
            project_path=parsed.project_path,
            pretasks=pretasks,
            run_time_limit_minutes=parsed.run_time_limit_minutes,
            plan_env=dict(parsed.plan_env),
            extra_env=dict(parsed.extra_env),
            secrets=list(parsed.secrets),
            desktop=self._desktop_target(),
        )

        async def body(job: ServiceJob) -> dict[str, Any]:
            account.pretask_job = job
            try:
                await account.pretasks.run(run_request)
            except asyncio.CancelledError:
                return self._failure("cancelled", CANCELLED_MESSAGE)
            except MaaFWPretaskError as exc:
                return self._failure(
                    "pretask_failed", str(exc), exception_type=type(exc).__name__
                )
            except Exception as exc:  # noqa: BLE001 - 起进程失败等
                return self._failure(
                    "run_failed", str(exc), exception_type=type(exc).__name__
                )
            return {"ok": True}

        return self._start_account_job(account, "pretask", body, stoppable=True)

    async def pretask_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("pretask", request)

    async def pretask_stop(self, request: Any = None) -> dict[str, Any]:
        """只取消作业任务、不杀进程（进程留给收尾的 ``pretask_kill``，同原来被取消时的行为）。"""

        return self._stop("pretask", request)

    async def pretask_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("pretask", request)

    async def pretask_kill_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("pretask_kill_start", request)
        if failure is not None:
            return failure
        account = self._account(parsed.account)
        if account is None:
            return self._unknown_account()

        async def body(job: ServiceJob) -> dict[str, Any]:
            account.pretask_job = job
            await account.pretasks.stop()
            return {"ok": True}

        return self._start_account_job(account, "pretask_kill", body, stoppable=False)

    async def pretask_kill_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("pretask_kill", request)

    async def pretask_kill_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("pretask_kill", request)

    async def pretask_exit_watch_start(self, request: Any = None) -> dict[str, Any]:
        """当场拍快照（同 ``MaaFWPretaskRunner.exit_confirmation``），作业等它们确认退出。

        没开过账号（``account`` 为 null）时没有要等的，作业当场以确认结束——与原来没跑过运行前设置
        时 ``confirm()`` 立即返回真一致。之后即使账号被 ``account_close``，作业照常等完。
        """

        parsed, failure = self._parse("pretask_exit_watch_start", request)
        if failure is not None:
            return failure
        if parsed.account is None:

            async def nothing(_job: ServiceJob) -> dict[str, Any]:
                return {"ok": True, "confirmed": True}

            started = self._handles.start(
                "pretask_exit_watch", nothing, stop_grace=None
            )
            return started
        account = self._account(parsed.account, allow_closing=True)
        if account is None:
            return self._unknown_account()
        confirm = account.pretasks.exit_confirmation()
        # after_scope：调用方此刻的进程作用域（作业任务在这次调用里建，读的也是它），收尾后再等确认
        scope = self._process_scope() if parsed.after_scope else None

        async def body(job: ServiceJob) -> dict[str, Any]:
            finished = getattr(scope, "finished", None)
            if finished is not None:
                await finished.wait()
            return {"ok": True, "confirmed": bool(await confirm())}

        return self._start_account_job(
            account, "pretask_exit_watch", body, stoppable=False
        )

    async def pretask_exit_watch_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("pretask_exit_watch", request)

    async def pretask_exit_watch_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("pretask_exit_watch", request)

    # ------------------------------------------------------------------
    # 跑一份计划
    # ------------------------------------------------------------------

    async def plan_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("plan_start", request)
        if failure is not None:
            return failure
        account = self._account(parsed.account)
        if account is None:
            return self._unknown_account()
        from pathlib import Path

        from maafw_interface.interface.agent_command import MaaFWAgentCommandPlan
        from maafw_interface.interface.models import MaaFWAgent
        from maafw_interface.runner.models import MaaFWDeviceConfig, MaaFWRunPlan
        from pydantic import ValidationError

        from .plan_run import MaaFWPlanRun, MaaFWPlanRunRequest

        try:
            plan = MaaFWRunPlan.model_validate(parsed.plan)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("plan",)
            )
        declared = []
        for index, item in enumerate(parsed.declared_agents):
            try:
                declared.append(MaaFWAgent.model_validate(item))
            except ValidationError as exc:
                return contract.invalid_request(
                    contract.error_entries(exc), prefix=("declared_agents", index)
                )
        # 整份 dump 时 declaredAgents 被 exclude 丢掉，另带过来再装回去（§11 D1）
        plan.declaredAgents = declared
        try:
            device_config = MaaFWDeviceConfig.model_validate(parsed.device_config)
        except ValidationError as exc:
            return contract.invalid_request(
                contract.error_entries(exc), prefix=("device_config",)
            )
        agent_plans = None
        if parsed.agent_plans is not None:
            try:
                agent_plans = tuple(
                    MaaFWAgentCommandPlan.model_validate(item)
                    for item in parsed.agent_plans
                )
            except ValidationError as exc:
                return contract.invalid_request(
                    contract.error_entries(exc), prefix=("agent_plans",)
                )
        # 这次调用里读：桌面游戏刚启动的时刻、桌面分身目标、ModAVD 的模拟器入口
        if parsed.game_start_source == "desktop":
            game_started_at = account.desktop.started_at
        else:
            game_started_at = parsed.game_started_at
        avd_emulator = (
            await self._emulator(parsed.avd.emulator_id)
            if parsed.avd is not None
            else None
        )
        root = parsed.runtime_pool_root
        run_request = MaaFWPlanRunRequest(
            project_path=Path(parsed.project_path),
            plan=plan,
            device_config=device_config,
            runtime_pool_root=Path(root) if root else None,
            runtime_pool_id=parsed.runtime_pool_id,
            lease_owner=parsed.lease_owner,
            run_time_limit_minutes=parsed.run_time_limit_minutes,
            attachment_root=Path(parsed.attachment_root),
            task_time_limit_seconds=parsed.task_time_limit_seconds,
            task_time_limit_overrides=dict(parsed.task_time_limit_overrides),
            task_deadlines=dict(parsed.task_deadlines),
            loop_guard=parsed.loop_guard,
            run_secrets=list(parsed.run_secrets),
            project_log_secrets=list(parsed.project_log_secrets),
            redaction_notice=parsed.redaction_notice,
            game_started_at=game_started_at,
            game_start_disk_quiet=parsed.game_start_disk_quiet,
            game_wait_seconds=parsed.game_wait_seconds,
            proxy_url=parsed.proxy_url,
            agent_plans=agent_plans,
            extra_env=dict(parsed.extra_env),
            desktop=self._desktop_target(),
            avd_emulator=avd_emulator,
        )
        services = getattr(self, "services", None)

        async def body(job: ServiceJob) -> dict[str, Any]:
            from .plan_run import MaaFWRunTimeoutError, MaaFWTaskDeadlineExpired

            run = MaaFWPlanRun(
                run_request,
                lambda event: _forward_event(job.emit, event),
                services=services,
            )

            def detail(**extra: Any) -> dict[str, Any]:
                return {**_plan_extras(run), **extra}

            try:
                outcome = await run.run()
            except asyncio.CancelledError:
                return self._failure("cancelled", CANCELLED_MESSAGE, **detail())
            except MaaFWRunTimeoutError as exc:
                return self._failure(
                    "run_timeout",
                    str(exc),
                    **detail(exception_type=type(exc).__name__),
                )
            except MaaFWTaskDeadlineExpired as exc:
                return self._failure(
                    "task_deadline_expired",
                    str(exc),
                    **detail(
                        task_name=exc.task_name, exception_type=type(exc).__name__
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - 借环境失败、ModAVD 门槛、worker 没回结果……
                return self._failure(
                    "run_failed", str(exc), **detail(exception_type=type(exc).__name__)
                )
            return {
                "ok": True,
                "result": outcome.result.model_dump(mode="json"),
                **_plan_extras(run),
            }

        return self._start_account_job(account, "plan", body, stoppable=True)

    async def plan_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("plan", request)

    async def plan_stop(self, request: Any = None) -> dict[str, Any]:
        """取消作业任务，走原来被取消时的路径：先结束 worker，收日志、附件，还环境。"""

        return self._stop("plan", request)

    async def plan_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("plan", request)

    # ------------------------------------------------------------------
    # 停用、退出
    # ------------------------------------------------------------------

    def service_blockers(self) -> list[str]:
        """``teardown_blockers`` 的内容：只读内存表，不等。

        N 数有在途作业（含已脱手、还在跑的 ``desktop_quit``、``pretask_kill``）的账号；专项还走旧路径、
        直接跑 ``MaaFWPlanRun`` 的那些运行照旧也算（``active_plan_runs`` 减去作业里跑着的计划）。
        """

        from .plan_run import active_plan_runs

        active_accounts = [
            account for account in self._accounts.values() if account.jobs
        ]
        service_plans = len(self._handles.active(("plan",)))
        legacy_runs = max(0, active_plan_runs() - service_plans)
        count = len(active_accounts) + legacy_runs
        if count:
            return [BLOCKER_RUNS.format(count=count)]
        return []

    async def shutdown_services(self, *, teardown: bool) -> None:
        """停用（``teardown=False``）或退出（``teardown=True``）时收掉句柄表与账号。

        - 停用：对在途作业置停止、取消作业任务；清空句柄表与账号。
        - 退出：对在途作业置停止（没有取消点的清理不取消），在途作业最多等 2 秒；还挂着 Unity 分辨率
          覆盖的账号只恢复注册表、不关游戏；清空句柄表与账号。
        """

        if teardown:
            await self._handles.shutdown(TEARDOWN_WAIT_SECONDS, "teardown")
            for account in list(self._accounts.values()):
                desktop = account.desktop
                restore = getattr(desktop, "_restore_resolution_override", None)
                if restore is None:
                    continue
                try:
                    await restore()
                except Exception as exc:  # noqa: BLE001 - 退出收尾尽力而为
                    logger.warning(f"MFW 运行插件退出时恢复游戏分辨率失败: {exc}")
        else:
            self._handles.abort_all("disable")
        self._accounts.clear()


def _plan_extras(run: Any) -> dict[str, Any]:
    """计划作业结束时运行对象上的附件、原生报错行、agent 计划（失败时也有）。"""

    plans = run.agent_plans
    return {
        "attachments": [
            {
                "path": str(item.path),
                "kind": item.kind,
                "role": item.role,
                "display_name": item.display_name,
            }
            for item in run.attachments
        ],
        "native_errors": [str(line) for line in run.native_errors],
        "agent_plans": None
        if plans is None
        else [plan.model_dump(mode="json") for plan in plans],
    }


def _done(failure: dict[str, Any]) -> Any:
    async def value() -> dict[str, Any]:
        return failure

    return value()


__all__ = [
    "ACCOUNT_BUSY_MESSAGE",
    "BLOCKER_RUNS",
    "TEARDOWN_WAIT_SECONDS",
    "UNKNOWN_ACCOUNT_MESSAGE",
    "UNKNOWN_HANDLE_MESSAGE",
    "RunnerServices",
]
