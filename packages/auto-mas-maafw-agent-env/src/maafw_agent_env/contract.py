"""agent 环境服务（``maafw.agent_env.v1.*``）的请求契约：每个操作一个 pydantic 模型。

口径见 MFW 服务化实施方案 §2.2 与 §3.1：

- 请求是只含 JSON 值的字典，路径一律字符串；
- 多出来的键忽略（``extra="ignore"``，顶层与嵌套都是）：专项共用库升级后多带的可选字段，
  旧提供方照旧受理；服务层只按键名记一条 debug，不记值；
- 缺必填字段、类型不对回 ``invalid_request``：message 只带出错字段的路径，``detail.errors``
  只放 ``loc`` 与 ``type``——pydantic 的 ``errors()`` / ``json()`` 带输入原值（请求里有代理凭据），
  ``hide_input_in_errors`` 只管 ``str(exc)``。

本模块只依赖 pydantic，不导入宿主、SDK 与本包别的模块：专项共用库的同仓测试要导入它核对
请求字典的键。
"""

from __future__ import annotations

import types
import typing
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: 借环境租约的缺省有效期（与 ``runtime_lease.DEFAULT_RUNTIME_LEASE_TTL_SECONDS`` 同值）。
DEFAULT_LEASE_TTL_SECONDS = 24 * 60 * 60
#: 借环境的缺省租约主人（与 ``borrow_runtime_environment`` 的缺省值相同）。
DEFAULT_LEASE_OWNER = "automas-maafw-runner"

CODE_INVALID_REQUEST = "invalid_request"
#: ``invalid_request`` 的文案前缀；后面接出错字段的路径。
INVALID_REQUEST_PREFIX = "agent 环境积木收到的请求格式不对："


class _Request(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class EmptyRequest(_Request):
    """``version``、``runtime_route``、``storage_info``：不收参数。"""


class ProjectPathRequest(_Request):
    """``runtime_check``：项目有效根。"""

    project_path: str


class BorrowStartRequest(_Request):
    project_path: str
    runtime_pool_root: str | None = None
    runtime_pool_id: str | None = None
    lease_owner: str = DEFAULT_LEASE_OWNER
    #: 缺省 86400；显式给 null 表示租约不设有效期（与原函数的 ``None`` 同义）。
    lease_ttl_seconds: float | None = DEFAULT_LEASE_TTL_SECONDS
    #: 运行计划的 ``declaredAgents``，每项是 ``MaaFWAgent.model_dump(mode="json", by_alias=True)``。
    agents: list[dict[str, Any]] = Field(default_factory=list)
    agent_env_root: str | None = None
    #: 子进程代理；null / 空串 = 不注入。
    proxy_url: str | None = None


class BorrowReturnRequest(_Request):
    """借到的四个标识原样交回；不依赖句柄表，提供方重载过也能还。"""

    runtime_pool_root: str | None = None
    runtime_id: str | None = None
    lease_id: str | None = None
    binding_version: str | None = None


class EnvLookupRequest(_Request):
    project_path: str
    want_previously_prepared: bool = False


class PrepareStartRequest(_Request):
    project_path: str
    runtime_pool_root: str | None = None
    runtime_pool_id: str | None = None
    #: 最终生效的代理（「没解析过就跟随全局」由调用方补好）；null / 空串 = 不注入。
    proxy_url: str | None = None
    lenient_health_check: bool = False
    store_cache: bool = False
    fallback_fingerprint: str | None = None
    import_check: Literal["off", "warn"] = "off"


class TrialStartRequest(_Request):
    project_path: str
    runtime_pool_root: str | None = None
    proxy_url: str | None = None
    previous_version: str | None = None


class ReconcileStartRequest(_Request):
    target: Literal["runtime_pool", "agent_venvs"]
    keep_paths: list[str]
    reason: str | None = None
    updated_project_path: str | None = None
    previous_version: str | None = None
    detach: bool = False


class CachePruneRequest(_Request):
    keep_project_paths: list[str]


class PollRequest(_Request):
    handle: str
    cursor: int = 0
    wait: float = 0.0
    limit: int | None = None


class StopRequest(_Request):
    handle: str
    #: 停止原因（``cancelled`` / ``stop_requested``）；本块不区分，收下不用。
    reason: str | None = None


class CloseRequest(_Request):
    handle: str


#: 有句柄的四族；``reconcile`` 没有取消点，不登记 ``_stop``。
HANDLE_FAMILIES: dict[str, type[_Request]] = {
    "borrow": BorrowStartRequest,
    "prepare": PrepareStartRequest,
    "trial": TrialStartRequest,
    "reconcile": ReconcileStartRequest,
}
STOPPABLE_FAMILIES = frozenset({"borrow", "prepare", "trial"})

#: 22 个操作名 → 请求模型。
REQUEST_MODELS: dict[str, type[_Request]] = {
    "version": EmptyRequest,
    "runtime_route": EmptyRequest,
    "runtime_check": ProjectPathRequest,
    "storage_info": EmptyRequest,
    "borrow_return": BorrowReturnRequest,
    "env_lookup": EnvLookupRequest,
    "cache_prune": CachePruneRequest,
}
for _family, _model in HANDLE_FAMILIES.items():
    REQUEST_MODELS[f"{_family}_start"] = _model
    REQUEST_MODELS[f"{_family}_poll"] = PollRequest
    if _family in STOPPABLE_FAMILIES:
        REQUEST_MODELS[f"{_family}_stop"] = StopRequest
    REQUEST_MODELS[f"{_family}_close"] = CloseRequest
del _family, _model

#: 本块提供的操作名（服务名是 ``maafw.agent_env.v1.<操作>``）。
OPERATIONS: tuple[str, ...] = tuple(REQUEST_MODELS)


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
    fields = model.model_fields
    known: dict[str, Any] = {}
    for name, info in fields.items():
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
    "DEFAULT_LEASE_OWNER",
    "DEFAULT_LEASE_TTL_SECONDS",
    "HANDLE_FAMILIES",
    "INVALID_REQUEST_PREFIX",
    "OPERATIONS",
    "REQUEST_MODELS",
    "STOPPABLE_FAMILIES",
    "BorrowReturnRequest",
    "BorrowStartRequest",
    "CachePruneRequest",
    "CloseRequest",
    "EmptyRequest",
    "EnvLookupRequest",
    "PollRequest",
    "PrepareStartRequest",
    "ProjectPathRequest",
    "ReconcileStartRequest",
    "StopRequest",
    "TrialStartRequest",
    "error_entries",
    "invalid_request",
    "parse_request",
    "unknown_keys",
]
