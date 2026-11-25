#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""项目（``maafw.project.v1.*``，33 个）与项目更新（``maafw.project_update.v1.*``，13 个）服务的请求契约。

口径见 MFW 服务化实施方案 §2.2、§3.3（细节照同目录 ``契约-maafw_project_update.md``）：

- 请求是只含 JSON 值的字典，路径一律字符串，时刻一律 ISO 8601 字符串；
- 多出来的键忽略（``extra="ignore"``，顶层与嵌套都是）：专项共用库升级后多带的可选字段，旧提供方
  照旧受理；服务层只按键名记一条 debug，不记值；
- 缺必填字段、类型不对回 ``invalid_request``：message 只带出错字段的路径，``detail.errors`` 只放
  ``loc`` 与 ``type``——请求里有托管级代理（可能带账号密码）与 Mirror 酱 CDK，pydantic 的
  ``errors()`` / ``json()`` 带输入原值，``hide_input_in_errors`` 只管 ``str(exc)``。

本模块只依赖 pydantic，不导入宿主、SDK 与本包别的模块：专项共用库的同仓测试要导入它核对请求字典的键。
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT = "maafw.project.v1"
PROJECT_UPDATE = "maafw.project_update.v1"

CODE_INVALID_REQUEST = "invalid_request"
#: ``invalid_request`` 的文案前缀；后面接出错字段的路径。
INVALID_REQUEST_PREFIX = "项目积木收到的请求格式不对："


class _Request(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class ManagedRecordPayload(_Request):
    """托管记录的字典形（字段同 ``owners.ManagedRecord``，由专项共用库 ``record_payload`` 生成）。

    ``proxy_address`` / ``mirror_cdk`` 是机密：不进 repr，不进日志。
    """

    uid: str
    kind: str = ""
    order: int = 0
    name: str | None = None
    source_path: str | None = None
    report: str | dict[str, Any] | None = None
    source_version: str | None = None
    imported_at: str | None = None
    follow_source: bool = False
    channel: str | None = None
    update_source: str | None = None
    auto_update_mode: str | None = None
    package_mode: str | None = None
    proxy_address: str | None = Field(default=None, repr=False)
    mirror_cdk: str | None = Field(default=None, repr=False)
    running: bool = False


class EmptyRequest(_Request):
    """``version``：不收参数。"""


class OwnerRegisterRequest(_Request):
    name: str
    prefix: str


class OwnerUnregisterRequest(_Request):
    name: str


class ScriptRequest(_Request):
    """``managed_find`` / ``project_peek`` / ``run_reserve``：只带托管 id。"""

    script_id: str


class ProjectContextRequest(_Request):
    record: ManagedRecordPayload
    with_view_import_check: bool = False


class RunReleaseRequest(_Request):
    key: str
    #: 修复作业的句柄：还在跑时把释放挂到它完成上。
    after_job: str | None = None
    on_job_error: Literal["keep", "release"] = "release"


class OpenStartRequest(_Request):
    script_id: str
    owner: str
    record: ManagedRecordPayload
    script_name: str = ""
    #: 这一轮开始的时刻（ISO 8601）；提供方还原成秒数交给会话，缺省 0（同旧请求的缺省）。
    round_started_at: datetime | None = None


class HandleRequest(_Request):
    """``open_release``：只带句柄。"""

    handle: str


class ConfirmStartRequest(_Request):
    script_id: str
    owner: str = ""
    record: ManagedRecordPayload
    phase: Literal["BeforeRun", "AfterRun"]
    stop_requested: bool = False


class FinishStartRequest(_Request):
    script_id: str
    owner: str = ""
    script_name: str = ""
    record: ManagedRecordPayload
    sync_group: bool
    round_started_at: float = 0.0


class RepairStartRequest(_Request):
    script_id: str
    script_name: str = ""
    record: ManagedRecordPayload
    kind: str
    already_checked: bool = False


class ViewEnsureStartRequest(_Request):
    script_id: str | None = None
    fallback_path: str = ""


class ScriptClonedStartRequest(_Request):
    source_id: str
    target_id: str
    owner: str
    source_record: ManagedRecordPayload


class ScriptRemovedStartRequest(_Request):
    script_id: str
    owner: str


class UpdateStartRequest(_Request):
    script_id: str
    owner: str = ""
    script_name: str = ""
    record: ManagedRecordPayload
    phase: Literal["BeforeRun", "AfterRun"]
    #: 任务参数里队列预下载交来的路径映射（值是路径字符串）。
    prefetch_paths: dict[str, Any] = Field(default_factory=dict)
    prefetch_token: str | None = None
    round_started_at: datetime | None = None
    stop_requested: bool = False


class ProjectJobRequest(_Request):
    """``prefetch_start`` / ``discover_start``。"""

    script_id: str
    owner: str = ""
    record: ManagedRecordPayload


class PrefetchDiscardRequest(_Request):
    token: str


class PollRequest(_Request):
    handle: str
    cursor: int = 0
    wait: float = 0.0
    limit: int | None = None


class StopRequest(_Request):
    handle: str
    #: 只有 ``open`` / ``confirm`` / ``update`` 认；缺省 ``cancelled``。
    reason: Literal["cancelled", "stop_requested"] | None = None


class CloseRequest(_Request):
    handle: str


#: 有句柄的族：``(服务名前缀, 族) → 请求模型``。
HANDLE_FAMILIES: dict[tuple[str, str], type[_Request]] = {
    (PROJECT, "open"): OpenStartRequest,
    (PROJECT, "confirm"): ConfirmStartRequest,
    (PROJECT, "finish"): FinishStartRequest,
    (PROJECT, "repair"): RepairStartRequest,
    (PROJECT, "view_ensure"): ViewEnsureStartRequest,
    (PROJECT, "script_cloned"): ScriptClonedStartRequest,
    (PROJECT, "script_removed"): ScriptRemovedStartRequest,
    (PROJECT_UPDATE, "update"): UpdateStartRequest,
    (PROJECT_UPDATE, "prefetch"): ProjectJobRequest,
    (PROJECT_UPDATE, "discover"): ProjectJobRequest,
}
#: 没有取消点、不登记 ``_stop`` 的族（实施方案 §3.0）。
NO_STOP_FAMILIES = frozenset(
    {"finish", "view_ensure", "script_cloned", "script_removed"}
)

#: 服务名（``<前缀>.<操作>``）→ 请求模型。
REQUEST_MODELS: dict[str, type[_Request]] = {
    f"{PROJECT}.version": EmptyRequest,
    f"{PROJECT}.owner_register": OwnerRegisterRequest,
    f"{PROJECT}.owner_unregister": OwnerUnregisterRequest,
    f"{PROJECT}.managed_find": ScriptRequest,
    f"{PROJECT}.project_context": ProjectContextRequest,
    f"{PROJECT}.project_peek": ScriptRequest,
    f"{PROJECT}.run_reserve": ScriptRequest,
    f"{PROJECT}.run_release": RunReleaseRequest,
    f"{PROJECT}.open_release": HandleRequest,
    f"{PROJECT_UPDATE}.prefetch_discard": PrefetchDiscardRequest,
}
for (_prefix, _family), _model in HANDLE_FAMILIES.items():
    REQUEST_MODELS[f"{_prefix}.{_family}_start"] = _model
    REQUEST_MODELS[f"{_prefix}.{_family}_poll"] = PollRequest
    if _family not in NO_STOP_FAMILIES:
        REQUEST_MODELS[f"{_prefix}.{_family}_stop"] = StopRequest
    REQUEST_MODELS[f"{_prefix}.{_family}_close"] = CloseRequest
del _prefix, _family, _model

#: 本插件提供的全部按操作拆分服务名。
SERVICE_NAMES: tuple[str, ...] = tuple(REQUEST_MODELS)


def method_name(service: str) -> str:
    """服务名 → 插件上的方法名：``maafw.project.v1.open_start`` → ``project_open_start``，
    ``maafw.project_update.v1.update_start`` → ``project_update_update_start``。"""

    prefix, _, op = service.rpartition(".")
    return ("project_update_" if prefix == PROJECT_UPDATE else "project_") + op


def _nested_model(annotation: Any) -> type[BaseModel] | None:
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


def invalid_request(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """``invalid_request`` 结果：文案只带字段路径，``detail`` 只带 ``loc`` / ``type``。"""

    paths: list[str] = []
    for item in errors:
        path = ".".join(str(part) for part in item["loc"]) or "请求"
        if path not in paths:
            paths.append(path)
    return {
        "ok": False,
        "code": CODE_INVALID_REQUEST,
        "message": INVALID_REQUEST_PREFIX + "、".join(paths),
        "detail": {"errors": [dict(item) for item in errors]},
    }


def parse_request(
    service: str, request: Any
) -> tuple[_Request | None, dict[str, Any] | None, list[str]]:
    """校验 ``service`` 的请求：返回 ``(模型, None, 不认识的键)`` 或 ``(None, invalid_request 结果, [])``。

    ``request`` 为 ``None`` 时按空字典处理。
    """

    model = REQUEST_MODELS[service]
    data = {} if request is None else request
    try:
        parsed = model.model_validate(data)
    except ValidationError as exc:
        return None, invalid_request(error_entries(exc)), []
    return parsed, None, unknown_keys(model, data)


def record_dict(record: ManagedRecordPayload) -> dict[str, Any]:
    """校验过的托管记录 → 字典（交给 ``ManagedRecord.from_payload``）。"""

    return record.model_dump()


__all__ = [
    "CODE_INVALID_REQUEST",
    "HANDLE_FAMILIES",
    "INVALID_REQUEST_PREFIX",
    "NO_STOP_FAMILIES",
    "PROJECT",
    "PROJECT_UPDATE",
    "REQUEST_MODELS",
    "SERVICE_NAMES",
    "ManagedRecordPayload",
    "error_entries",
    "invalid_request",
    "method_name",
    "parse_request",
    "record_dict",
    "unknown_keys",
]
