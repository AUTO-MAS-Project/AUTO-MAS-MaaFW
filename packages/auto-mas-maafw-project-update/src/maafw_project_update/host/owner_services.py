#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""新形属主（``maafw.owner.<专项>.v1.*``，每个方法一个服务名）在项目更新这一侧的适配器。

专项经 ``maafw.project.v1.owner_register(name, prefix)`` 登记的是「属主名 → 服务名前缀」；这里把前缀
包装成项目服务使用的属主入口，``owners.py`` 以下的代码不用改：

- ``list_managed`` / ``read_managed`` / ``check_source_path``、``plan_rules``、``project_mismatch`` 是同步服务
  （项目更新在事件循环与工作线程上同步问属主），``lock_managed`` / ``unlock_managed`` / ``write_record`` 是
  异步服务；每次调用都经解析器 ``get`` 现取服务，不缓存服务对象。
- 出入都是只含 JSON 值的字典，这里还原成 ``owners`` 的数据类（``ManagedRecord.from_payload`` 一处负责，
  ``imported_at`` 在那里从 ISO 字符串转回 datetime）。
- 同步服务撞上属主暂停准入（``PluginBusyError``）不重试、按「属主答不上来」处理：同步调用多在事件
  循环线程上，退避等待会把事件循环一起停住（属主的暂停本身也要事件循环）。异步服务按解析库的
  忙重试走。

本模块不导入任何专项。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from maafw_interface.service_calls import (
    REASON_NOT_REGISTERED,
    ServiceUnavailable,
    call_service,
    is_plugin_busy_error,
)

from . import owners


class OwnerUnavailable(RuntimeError):
    """属主服务此刻拿不到（没登记、注册表已封、暂停准入）。"""


class _GetResolver:
    """把 ``services.get`` 包成解析库认的 ``require``：取不到抛 :class:`ServiceUnavailable`。"""

    def __init__(self, services: Any) -> None:
        self._services = services

    def require(self, name: str) -> Any:
        method = self._services.get(name)
        if method is None:
            raise ServiceUnavailable(name, REASON_NOT_REGISTERED)
        return method


def _patch_payload(patch: owners.RecordPatch) -> dict[str, Any]:
    """``RecordPatch`` → 写回补丁字典：只放给了值的键（``UNSET`` = 键不在）。"""

    data: dict[str, Any] = {}
    for key in ("source_path", "report", "source_version", "imported_at", "channel"):
        value = getattr(patch, key)
        if value is owners.UNSET:
            continue
        if key == "source_path" and value is not None and hasattr(value, "__fspath__"):
            value = str(value.__fspath__())
        if key == "imported_at" and value is not None and not isinstance(value, str):
            isoformat = getattr(value, "isoformat", None)
            value = str(isoformat()) if callable(isoformat) else str(value)
        data[key] = value
    return data


class _ProjectMismatch:
    """属主「这个项目收不收」的判据（属主服务 ``project_mismatch``，收项目目录）。

    旧形属主给的是收 interface 对象的函数；新形要的是目录：端点读好 interface 之后带上它所在的目录
    调（``wants_project_root``）。只给 interface 时没法问，按「不拦」处理。
    """

    wants_project_root = True

    def __init__(self, entry: ServiceOwnerEntry) -> None:
        self._entry = entry

    def __call__(
        self, interface: Any = None, *, project_root: Any = None
    ) -> str | None:
        if project_root is None:
            return None
        reply = self._entry._call_sync(
            "project_mismatch", {"project_root": str(project_root)}
        )
        message = reply.get("message")
        return None if message is None else str(message)


class ServiceOwnerEntry:
    """一个属主服务名前缀 ``prefix`` 的入口。"""

    owner_protocol = owners.OWNER_PROTOCOL

    def __init__(self, name: str, prefix: str, services: Any) -> None:
        self.name = name
        self.prefix = prefix
        self._services = services

    def available(self) -> bool:
        """属主服务此刻登记着（按 ``list`` 看）。"""

        return self._services.get(f"{self.prefix}.list") is not None

    def _method(self, op: str) -> Any:
        method = self._services.get(f"{self.prefix}.{op}")
        if method is None:
            raise OwnerUnavailable(f"托管属主 {self.name} 的服务 {op} 不可用")
        return method

    def _call_sync(self, op: str, request: Mapping[str, Any]) -> dict[str, Any]:
        method = self._method(op)
        try:
            value = method(dict(request))
        except Exception as exc:
            if is_plugin_busy_error(exc):
                raise OwnerUnavailable(f"托管属主 {self.name} 暂时不可用") from exc
            raise
        if inspect.isawaitable(value):
            if inspect.iscoroutine(value):
                value.close()
            raise TypeError(f"托管属主 {self.name} 的服务 {op} 应是同步的")
        if not isinstance(value, Mapping):
            raise TypeError(f"托管属主 {self.name} 的服务 {op} 回的不是字典")
        return dict(value)

    async def _call_async(self, op: str, request: Mapping[str, Any]) -> dict[str, Any]:
        try:
            value = await call_service(
                _GetResolver(self._services), f"{self.prefix}.{op}", request
            )
        except ServiceUnavailable as exc:
            raise OwnerUnavailable(f"托管属主 {self.name} 的服务 {op} 不可用") from exc
        if not isinstance(value, Mapping):
            raise TypeError(f"托管属主 {self.name} 的服务 {op} 回的不是字典")
        return dict(value)

    # -- 读（同步） ---------------------------------------------------------

    def list_managed(self) -> owners.OwnerListing:
        reply = self._call_sync("list", {})
        items = tuple(
            owners.ManagedRecord.from_payload(item)
            for item in reply.get("items") or ()
            if isinstance(item, Mapping)
        )
        return owners.OwnerListing(ready=bool(reply.get("ready")), items=items)

    def read_managed(self, script_id: str) -> owners.ReadResult:
        reply = self._call_sync("read", {"script_id": str(script_id)})
        record = reply.get("record")
        return owners.ReadResult(
            str(reply.get("status") or "missing"),  # type: ignore[arg-type]
            record=(
                owners.ManagedRecord.from_payload(record)
                if isinstance(record, Mapping)
                else None
            ),
            detail=str(reply.get("detail") or ""),
        )

    def check_source_path(self, script_id: str, path: str) -> owners.PathCheck:
        reply = self._call_sync(
            "check_source_path", {"script_id": str(script_id), "path": path}
        )
        return owners.PathCheck(
            str(reply.get("status") or "error"),  # type: ignore[arg-type]
            str(reply.get("detail") or ""),
        )

    @property
    def plan_rules(self) -> Any:
        """建计划规则表（``MaaFWPlanRules``）；属主答不上来时为 None（调用方当空表）。"""

        from maafw_interface.interface.plan_rules import MaaFWPlanRules

        try:
            reply = self._call_sync("plan_rules", {})
        except OwnerUnavailable as exc:
            owners.logger.warning(f"{exc}，建计划规则按空表处理")
            return None
        rules = reply.get("rules")
        if not isinstance(rules, Mapping):
            rules = {key: value for key, value in reply.items() if key != "ok"}
        return MaaFWPlanRules.from_dict(rules)

    @property
    def project_mismatch(self) -> Callable[..., str | None]:
        return _ProjectMismatch(self)

    # -- 写（异步） ---------------------------------------------------------

    async def lock_managed(self, script_id: str) -> str | None:
        try:
            reply = await self._call_async("lock", {"script_id": str(script_id)})
        except OwnerUnavailable:
            return None
        ticket = reply.get("ticket")
        return None if ticket is None else str(ticket)

    async def unlock_managed(self, script_id: str, ticket: str) -> None:
        await self._call_async(
            "unlock", {"script_id": str(script_id), "ticket": ticket}
        )

    async def write_record(
        self, script_id: str, patch: owners.RecordPatch, *, ticket: str | None = None
    ) -> owners.WriteResult:
        request: dict[str, Any] = {
            "script_id": str(script_id),
            "patch": _patch_payload(patch),
            "ticket": ticket,
        }
        try:
            reply = await self._call_async("write", request)
        except OwnerUnavailable:
            return owners.WriteResult(
                False, "unavailable", "托管所属的专项不可用，导入记录没有写回"
            )
        if reply.get("ok"):
            return owners.WriteResult(True)
        reason = str(reply.get("reason") or "rejected")
        if reason not in ("rejected", "not_found", "unavailable"):
            reason = "rejected"
        return owners.WriteResult(
            False,
            reason,  # type: ignore[arg-type]
            str(reply.get("detail") or ""),
        )


__all__ = ["OwnerUnavailable", "ServiceOwnerEntry"]
