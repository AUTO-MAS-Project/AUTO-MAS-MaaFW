"""运行服务（``maafw.runner.v1.*``）的请求契约：每个操作一个 pydantic 模型。

口径见 MFW 服务化实施方案 §2.2 与 §3.2（细节照同目录 ``契约-maafw_runner.md``）：

- 请求是只含 JSON 值的字典，路径一律字符串；
- 多出来的键忽略（``extra="ignore"``，顶层与嵌套都是）：专项共用库升级后多带的可选字段，
  旧提供方照旧受理；服务层只按键名记一条 debug，不记值；
- 缺必填字段、类型不对回 ``invalid_request``：message 只带出错字段的路径，``detail.errors``
  只放 ``loc`` 与 ``type``——pydantic 的 ``errors()`` / ``json()`` 带输入原值（请求里有解密后的
  密码、打码值），``hide_input_in_errors`` 只管 ``str(exc)``。

本模块只依赖 pydantic，不导入宿主、SDK 与本包别的模块：专项共用库的同仓测试要导入它核对
请求字典的键。计划、设备配置、控制器这些大对象在这里只校验成字典，提供方再按解析库的模型还原。
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CODE_INVALID_REQUEST = "invalid_request"
#: ``invalid_request`` 的文案前缀；后面接出错字段的路径。
INVALID_REQUEST_PREFIX = "运行积木收到的请求格式不对："


class _Request(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class EmptyRequest(_Request):
    """``version``：不收参数。"""


class AccountOpenRequest(_Request):
    #: 归属，只进后端日志，例如 ``automas-script-maafw:<托管 id>``。
    owner: str
    #: 账号名，只进后端日志。
    label: str
    #: ``time.time()``；AttachOnly 兜底关闭的分界（``MaaFWDesktopGame.mark_run_started``）。
    run_started_at: float


class AccountRequest(_Request):
    """``account_close``、``pretask_kill_start``：只带账号句柄。"""

    account: str


class ExitWatchStartRequest(_Request):
    """``pretask_exit_watch_start``：账号句柄；没开过账号（检查没过）时为 null，当场确认。"""

    account: str | None = None


class DesktopSpec(_Request):
    """桌面游戏的 Spec（替掉 ``MaaFWDesktopGameSpec``，字段名不变）。"""

    launch_mode: str
    game_path: str | None = None
    launcher_path: str | None = None
    url: str = ""
    arguments: Any = None
    wait_seconds: Any = None
    unity_resolution: list[int] | None = None
    close_mode: str = "OnFailure"
    configured_hwnd: Any = None
    #: 只给收尾关游戏用：读游戏 / 启动器路径时的异常原文（``str(exc)``）。
    game_path_error: str | None = None
    launcher_path_error: str | None = None


class DesktopCheckRequest(_Request):
    spec: DesktopSpec


class _ControllerFields(_Request):
    #: 选中控制器的 ``MaaFWController.model_dump(mode="json", by_alias=True)``；interface 没加载时 null。
    controller: dict[str, Any] | None = None
    #: 可选：控制器名。interface 加载了却没找到控制器时，提供方在原来查控制器的那一步报
    #: 「未找到 controller: <名字>」（判定顺序不变）。
    controller_name: str | None = None
    #: 可选：interface 有没有加载；缺省按 ``controller`` 是否为 null 判。
    interface_loaded: bool | None = None


class DesktopLaunchStartRequest(_ControllerFields):
    account: str
    spec: DesktopSpec


class DesktopQuitStartRequest(_ControllerFields):
    account: str
    spec: DesktopSpec
    #: ``retry`` = 重试之间关 MAS 起的游戏（``close``）；``final`` = 最终收尾（``close_after_run``）。
    mode: Literal["retry", "final"]
    controller_type: str | None = None
    failed: bool = False


class DeviceAdbPathRequest(_Request):
    emulator_id: str
    device_uid: str
    configured_path: Any = None
    device_title: str | None = None
    address: str = ""
    #: 调用方缓存的上一次结果；null 时才按脚本配置、模拟器管理器、安装目录解析。
    host_adb_path: str | None = None
    ask_toolkit: Literal["never", "if_unresolved"] = "never"


class AdbProfile(_Request):
    """替掉 ``MaaFWAdbControlProfile``。"""

    emulator_type: str | None = None
    screencap_extra: bool = False
    input_extra: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


class EmulatorProcess(_Request):
    process_id: int | None = None
    process_started_at: float | None = None


class DeviceAdbConfigRequest(_Request):
    emulator_id: str
    target_id: str
    device_uid: str
    address: str
    adb_path: str | None = None
    #: 调用方缓存；null 时才建。
    profile: AdbProfile | None = None
    emulator_process: EmulatorProcess = Field(default_factory=EmulatorProcess)
    configured_screencap_methods: Any = None
    configured_input_methods: Any = None


class DeviceWin32ConfigRequest(_Request):
    controller: dict[str, Any]
    configured_hwnd: Any = None
    configured_screencap_method: Any = None
    configured_mouse_method: Any = None
    configured_keyboard_method: Any = None


class PretaskRerunCheckRequest(_Request):
    has_pretasks: bool
    client_reset: bool
    controller_type: str | None = None
    interface_loaded: bool = False
    controller_name: str | None = None
    controller: dict[str, Any] | None = None
    configured_hwnd: Any = None


class PretaskStartRequest(_Request):
    account: str
    project_path: str
    #: 计划的 ``pretasks``，每项是 ``MaaFWPretaskRunPlan`` 的 dump。
    pretasks: list[dict[str, Any]] = Field(default_factory=list)
    #: ``Run.RunTimeLimit``，0 / 空按 120。
    run_time_limit_minutes: Any = 0
    plan_env: dict[str, str] = Field(default_factory=dict)
    extra_env: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)


class AvdRef(_Request):
    emulator_id: str


class PlanStartRequest(_Request):
    account: str
    project_path: str
    #: ``MaaFWRunPlan.model_dump(mode="json")``；``declaredAgents`` 带 ``exclude=True``、整份 dump 时丢掉，
    #: 另由 ``declared_agents`` 带（实施方案 §11 D1）。
    plan: dict[str, Any]
    #: 每项 ``MaaFWAgent.model_dump(mode="json", by_alias=True)``，提供方还原后交给借环境。
    declared_agents: list[dict[str, Any]] = Field(default_factory=list)
    device_config: dict[str, Any]
    runtime_pool_root: str | None = None
    runtime_pool_id: str = ""
    lease_owner: str
    run_time_limit_minutes: int
    attachment_root: str
    task_time_limit_seconds: int = 0
    task_time_limit_overrides: dict[str, int] = Field(default_factory=dict)
    #: 宿主进程里的 ``time.monotonic()`` 截止时刻（两边同一进程）。
    task_deadlines: dict[str, float] = Field(default_factory=dict)
    loop_guard: bool = False
    run_secrets: list[str] = Field(default_factory=list)
    project_log_secrets: list[str] = Field(default_factory=list)
    redaction_notice: str | None = None
    #: ``desktop``：取账号桌面游戏的 ``started_at``（Win32）；``given``：用 ``game_started_at``（ADB）。
    game_start_source: Literal["desktop", "given"] = "given"
    game_started_at: float | None = None
    game_start_disk_quiet: bool = False
    game_wait_seconds: Any = 0
    proxy_url: str | None = None
    #: 沿用的 agent 命令计划（同一账号这一轮的重试）；null 时用这次借环境算出的。
    agent_plans: list[dict[str, Any]] | None = None
    extra_env: dict[str, str] = Field(default_factory=dict)
    #: ModAVD：提供方在这次调用里取模拟器入口过 MaaFramework 版本门槛；其余设备 null。
    avd: AvdRef | None = None


class PollRequest(_Request):
    handle: str
    cursor: int = 0
    wait: float = 0.0
    limit: int | None = None


class StopRequest(_Request):
    handle: str
    #: 停止原因；本块不区分，收下不用。
    reason: str | None = None


class CloseRequest(_Request):
    handle: str


#: 有句柄的六族 → ``_start`` 的请求模型。
HANDLE_FAMILIES: dict[str, type[_Request]] = {
    "desktop_launch": DesktopLaunchStartRequest,
    "desktop_quit": DesktopQuitStartRequest,
    "pretask": PretaskStartRequest,
    "pretask_kill": AccountRequest,
    "pretask_exit_watch": ExitWatchStartRequest,
    "plan": PlanStartRequest,
}
#: 登记 ``_stop`` 的族；另外三族的清理本来就不许中途放弃（实施方案 §3.0）。
STOPPABLE_FAMILIES = frozenset({"desktop_launch", "pretask", "plan"})

#: 29 个操作名 → 请求模型。
REQUEST_MODELS: dict[str, type[_Request]] = {
    "version": EmptyRequest,
    "account_open": AccountOpenRequest,
    "account_close": AccountRequest,
    "desktop_check": DesktopCheckRequest,
    "device_adb_path": DeviceAdbPathRequest,
    "device_adb_config": DeviceAdbConfigRequest,
    "device_win32_config": DeviceWin32ConfigRequest,
    "pretask_rerun_check": PretaskRerunCheckRequest,
}
for _family, _model in HANDLE_FAMILIES.items():
    REQUEST_MODELS[f"{_family}_start"] = _model
    REQUEST_MODELS[f"{_family}_poll"] = PollRequest
    if _family in STOPPABLE_FAMILIES:
        REQUEST_MODELS[f"{_family}_stop"] = StopRequest
    REQUEST_MODELS[f"{_family}_close"] = CloseRequest
del _family, _model

#: 本块提供的操作名（服务名是 ``maafw.runner.v1.<操作>``）。
OPERATIONS: tuple[str, ...] = tuple(REQUEST_MODELS)
#: 同步操作（工作线程里经同步调用助手调）；其余都是 async。
SYNC_OPERATIONS = frozenset({"desktop_check"})


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """字段注解里的请求模型（含 ``X | None``）；别的类型返回 ``None``。"""

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        for arg in typing.get_args(annotation):
            found = _nested_model(arg)
            if found is not None:
                return found
    return None


def unknown_keys(model: type[BaseModel], data: Any, prefix: str = "") -> list[str]:
    """请求里模型不认识的键（按路径，逐层），只给服务层记 debug 用，不带值。"""

    if not isinstance(data, Mapping):
        return []
    known: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        known[name] = info
        if info.alias:
            known[info.alias] = info
    found: list[str] = []
    for key, value in data.items():
        path = f"{prefix}{key}"
        info = known.get(key) if isinstance(key, str) else None
        if info is None:
            found.append(path)
            continue
        nested = _nested_model(info.annotation)
        if nested is not None:
            found.extend(unknown_keys(nested, value, f"{path}."))
    return found


def error_entries(exc: ValidationError) -> list[dict[str, Any]]:
    """校验错误只留 ``loc``（转 list）与 ``type``：``msg`` / ``ctx`` 可能夹带输入原值。"""

    return [
        {"loc": list(item["loc"]), "type": item["type"]}
        for item in exc.errors(include_input=False, include_url=False)
    ]


def invalid_request(
    errors: list[dict[str, Any]], *, prefix: tuple[Any, ...] = ()
) -> dict[str, Any]:
    """``invalid_request`` 结果：文案只带字段路径，``detail`` 只带 ``loc`` / ``type``。"""

    entries = [
        {"loc": [*prefix, *item["loc"]], "type": item["type"]} for item in errors
    ]
    paths: list[str] = []
    for item in entries:
        path = ".".join(str(part) for part in item["loc"]) or "请求"
        if path not in paths:
            paths.append(path)
    return {
        "ok": False,
        "code": CODE_INVALID_REQUEST,
        "message": INVALID_REQUEST_PREFIX + "、".join(paths),
        "detail": {"errors": entries},
    }


def parse_request(
    op: str, request: Any
) -> tuple[_Request | None, dict[str, Any] | None, list[str]]:
    """校验 ``op`` 的请求：返回 ``(模型, None, 不认识的键)`` 或 ``(None, invalid_request 结果, [])``。

    ``request`` 为 ``None`` 时按空字典处理（调用方可以不传参数调无参操作）。
    """

    model = REQUEST_MODELS[op]
    data = {} if request is None else request
    try:
        parsed = model.model_validate(data)
    except ValidationError as exc:
        return None, invalid_request(error_entries(exc)), []
    return parsed, None, unknown_keys(model, data)


__all__ = [
    "CODE_INVALID_REQUEST",
    "HANDLE_FAMILIES",
    "INVALID_REQUEST_PREFIX",
    "OPERATIONS",
    "REQUEST_MODELS",
    "STOPPABLE_FAMILIES",
    "SYNC_OPERATIONS",
    "AccountOpenRequest",
    "AccountRequest",
    "AdbProfile",
    "AvdRef",
    "CloseRequest",
    "DesktopCheckRequest",
    "DesktopLaunchStartRequest",
    "DesktopQuitStartRequest",
    "DesktopSpec",
    "DeviceAdbConfigRequest",
    "DeviceAdbPathRequest",
    "DeviceWin32ConfigRequest",
    "EmptyRequest",
    "EmulatorProcess",
    "ExitWatchStartRequest",
    "PlanStartRequest",
    "PollRequest",
    "PretaskRerunCheckRequest",
    "PretaskStartRequest",
    "StopRequest",
    "error_entries",
    "invalid_request",
    "parse_request",
    "unknown_keys",
]
