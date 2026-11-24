#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""内置专项的托管属主入口：按**确切类型**认领自己名下的托管（专项一侧）。

项目更新一侧（``tools/embedded/owners.py``）只经这里交出的普通数据知道托管还在不在、读写项目记录；
它不拿配置类，也不拿配置对象。三个内置专项各登记一个（通用 MFW 在 ``app/task/MaaFW/registration.py``，
M9A、MSS 在各自的 ``registration.py``）：认领用 ``type(config) is <类型>``，类型每次现取，不靠继承——
以后 M9A、MSS 的配置类不再继承 ``MaaFWConfig``，这里不用改。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from maafw_interface.interface.loader import load_interface_model_cached
from maafw_interface.interface.plan_rules import EMPTY_PLAN_RULES, MaaFWPlanRules

if TYPE_CHECKING:
    from maafw_interface.interface.models import MaaFWInterface
    from maafw_project_update.host.owners import (
        ManagedRecord,
        OwnerListing,
        PathCheck,
        ReadResult,
        RecordPatch,
        WriteResult,
    )

# 属主协议版本：项目更新（``maafw_project_update.host.owners.OWNER_PROTOCOL``）登记时比对，
# 对不上就当属主没登记。原先直接取项目更新的常量；这里是属主一侧实现的版本，写成字面值，
# 本模块顶层就不用导入项目更新插件。
OWNER_PROTOCOL = 1


def _owners() -> Any:
    """项目更新一侧的属主协议数据类（``ManagedRecord``、``ReadResult`` 等），用到时才取。"""

    from maafw_project_update.host import owners

    return owners


def _host_config() -> Any:
    from auto_mas_core.host.core import Config

    return Config


def _record(uid: str, config: Any, order: int) -> ManagedRecord:
    return _owners().ManagedRecord(
        uid=uid,
        kind=type(config).__name__.removesuffix("Config"),
        order=order,
        name=config.Info.Name,
        source_path=config.Info.Path,
        report=config.Embedded.Report,
        source_version=config.Embedded.SourceVersion,
        imported_at=config.Embedded.ImportedAt,
        follow_source=_follow_source(config),
        channel=config.Update.Channel,
        update_source=config.Update.Source,
        auto_update_mode=config.Update.AutoUpdateMode,
        package_mode=config.Update.PackageMode,
        proxy_address=config.Update.ProxyAddress,
        mirror_cdk=config.Update.MirrorChyanCDK,
        running=bool(getattr(config, "is_locked", False)),
    )


def _follow_source(config: Any) -> bool:
    try:
        return bool(config.Embedded.FollowSource)
    except Exception:  # noqa: BLE001 - 老配置没有这一项就是没开
        return False


def _patch_data(patch: RecordPatch) -> dict[str, Any]:
    """写回补丁 → 配置的分组字典；只放给了值的项，形状与原先各处直接写回时一致。"""

    UNSET = _owners().UNSET
    data: dict[str, Any] = {}
    if patch.source_path is not UNSET:
        data.setdefault("Info", {})["Path"] = patch.source_path
    embedded: dict[str, Any] = {}
    if patch.report is not UNSET:
        embedded["Report"] = json.dumps(patch.report, ensure_ascii=False)
    if patch.source_version is not UNSET:
        embedded["SourceVersion"] = patch.source_version
    if patch.imported_at is not UNSET:
        embedded["ImportedAt"] = patch.imported_at
    if embedded:
        data["Embedded"] = embedded
    if patch.channel is not UNSET:
        data.setdefault("Update", {})["Channel"] = patch.channel
    return data


def _json_text(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "__fspath__"):
        return str(value.__fspath__())
    return str(value)


def _json_time(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat()) if callable(isoformat) else str(value)


def _json_report(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_report(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_report(item) for item in value]
    return _json_text(value)


def record_payload(uid: str, config: Any, order: int = 0) -> dict[str, Any]:
    return {
        "uid": str(uid),
        "kind": type(config).__name__.removesuffix("Config"),
        "order": int(order),
        "name": _json_text(config.Info.Name),
        "source_path": _json_text(config.Info.Path),
        "report": _json_report(config.Embedded.Report),
        "source_version": _json_text(config.Embedded.SourceVersion),
        "imported_at": _json_time(config.Embedded.ImportedAt),
        "follow_source": _follow_source(config),
        "channel": _json_text(config.Update.Channel),
        "update_source": _json_text(config.Update.Source),
        "auto_update_mode": _json_text(config.Update.AutoUpdateMode),
        "package_mode": _json_text(config.Update.PackageMode),
        "proxy_address": _json_text(config.Update.ProxyAddress),
        "mirror_cdk": _json_text(config.Update.MirrorChyanCDK),
        "running": bool(getattr(config, "is_locked", False)),
    }


def _patch_dict_data(patch: Mapping[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if "source_path" in patch:
        data.setdefault("Info", {})["Path"] = patch["source_path"]
    embedded: dict[str, Any] = {}
    if "report" in patch:
        embedded["Report"] = json.dumps(patch["report"], ensure_ascii=False)
    if "source_version" in patch:
        embedded["SourceVersion"] = patch["source_version"]
    if "imported_at" in patch:
        embedded["ImportedAt"] = patch["imported_at"]
    if embedded:
        data["Embedded"] = embedded
    if "channel" in patch:
        data.setdefault("Update", {})["Channel"] = patch["channel"]
    return data


class OwnerKeyError(KeyError):
    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def _write_result(ok: bool, reason: str = "", detail: str = "") -> dict[str, Any]:
    if ok:
        return {"ok": True, "reason": "", "detail": ""}
    return {"ok": False, "reason": reason, "detail": detail, "code": reason, "message": detail}


OWNER_SERVICE_PREFIX = "maafw.owner.{owner}.v1"
OWNER_OPERATIONS: dict[str, str] = {
    "list": "owner_list",
    "read": "owner_read",
    "check_source_path": "owner_check_source_path",
    "plan_rules": "owner_plan_rules",
    "project_mismatch": "owner_project_mismatch",
    "lock": "owner_lock",
    "unlock": "owner_unlock",
    "write": "owner_write",
}
RECORD_PATCH_KEYS = (
    "source_path",
    "report",
    "source_version",
    "imported_at",
    "channel",
)


def owner_service_prefix(owner: str) -> str:
    return OWNER_SERVICE_PREFIX.format(owner=owner)


def owner_provides(owner: str) -> dict[str, str]:
    prefix = owner_service_prefix(owner)
    return {f"{prefix}.{operation}": method for operation, method in OWNER_OPERATIONS.items()}


class ConfigOwner:
    """宿主托管表里某一种确切类型的托管的属主（新形，回字典）。

    与专项配置类的确切类型判据一致：认领用 ``type(config) is <类型>``，类型每次现取；
    读不加锁、不要求托管完整加载（``list`` 另报 ``ready``）。专项在模块级建一份，交给
    :class:`OwnerServiceMixin`，自己写回项目记录时经 :func:`write_or_raise` 本地调它。
    """

    def __init__(
        self,
        name: str,
        config_type: Callable[[], type],
        *,
        host: Callable[[], Any] = _host_config,
        plan_rules: MaaFWPlanRules = EMPTY_PLAN_RULES,
        project_mismatch: Callable[[MaaFWInterface], str | None] | None = None,
    ) -> None:
        self.name = name
        self._config_type = config_type
        self._host = host
        self._tickets: dict[str, tuple[str, Any]] = {}
        self.plan_rules = plan_rules
        self.project_mismatch = project_mismatch

    def _mine(self, config: Any) -> bool:
        return type(config) is self._config_type()

    def _lookup(self, script_id: Any) -> tuple[str, Any] | _Miss:
        """找到时 ``(uid, config)``；没找到时 :class:`_Miss`（状态是 ``invalid_id`` / ``missing`` /
        ``not_mine``，带原话）。"""

        try:
            uid = uuid.UUID(str(script_id))
        except ValueError as exc:
            return _Miss("invalid_id", str(exc))
        try:
            config = self._host().ScriptConfig[uid]
        except KeyError as exc:
            return _Miss("missing", str(exc))
        except ValueError as exc:
            return _Miss("invalid_id", str(exc))
        if not self._mine(config):
            return _Miss("not_mine", "")
        return str(uid), config

    # -- 读（同步） ---------------------------------------------------------

    def list(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        host = self._host()
        # 有托管因所属插件不可用而旁挂时为假（宿主的 managed_configs_loaded）；旧宿主没有这个出口时
        # 退回旧名 script_config_loaded_intact
        loaded = getattr(host, "managed_configs_loaded", None)
        if loaded is None:
            loaded = host.script_config_loaded_intact
        ready = bool(loaded())
        items = [
            record_payload(str(uid), config, order)
            for order, (uid, config) in enumerate(host.ScriptConfig.items())
            if self._mine(config)
        ]
        return {"ok": True, "ready": ready, "items": items}

    def read(self, request: Mapping[str, Any]) -> dict[str, Any]:
        found = self._lookup(request.get("script_id"))
        if isinstance(found, _Miss):
            return {
                "ok": True,
                "status": found.status,
                "record": None,
                "detail": found.detail,
            }
        uid, config = found
        order = next(
            (
                index
                for index, key in enumerate(self._host().ScriptConfig.keys())
                if str(key) == uid
            ),
            0,
        )
        return {
            "ok": True,
            "status": "mine",
            "record": record_payload(uid, config, order),
            "detail": "",
        }

    def check_source_path(self, request: Mapping[str, Any]) -> dict[str, Any]:
        found = self._lookup(request.get("script_id"))
        if isinstance(found, _Miss):
            return {
                "ok": True,
                "status": "error",
                "detail": found.detail or "托管不存在",
            }
        _uid, config = found
        try:
            validated = type(config.Info).model_validate({"Path": request.get("path")})
        # 路径里的符号链接成环时，Python 3.12 的 Path.resolve 抛 RuntimeError
        except (ValueError, RuntimeError) as exc:
            return {"ok": True, "status": "error", "detail": str(exc)}
        if validated.Path is None:
            return {"ok": True, "status": "cleared", "detail": ""}
        return {"ok": True, "status": "ok", "detail": ""}

    def plan_rules_dict(
        self, request: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """``plan_rules``：规则表的字典形放在 ``rules`` 里（解析库 ``MaaFWPlanRules.from_dict`` 还原）。"""

        rules = self.plan_rules if self.plan_rules is not None else EMPTY_PLAN_RULES
        return {"ok": True, "rules": rules.to_dict()}

    def project_mismatch_message(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """``project_mismatch``：``project_root`` 下的项目不是本专项那种时给拒收原文，否则 ``None``。

        属主不挑项目时不读 interface；要读时用解析库的带缓存读法（项目服务在工作线程里调它，所以
        读法在模块顶层导入，线程里不做冷导入）。
        """

        hook = self.project_mismatch
        if not callable(hook):
            return {"ok": True, "message": None}
        interface = load_interface_model_cached(Path(str(request.get("project_root"))))
        return {"ok": True, "message": hook(interface)}

    # -- 写（异步） ---------------------------------------------------------

    async def lock(self, request: Mapping[str, Any]) -> dict[str, Any]:
        found = self._lookup(request.get("script_id"))
        if isinstance(found, _Miss):
            return {"ok": True, "ticket": None}
        uid, config = found
        ticket = await config.try_lock_x()
        if ticket is None:
            return {"ok": True, "ticket": None}
        ticket_id = uuid.uuid4().hex
        self._tickets[ticket_id] = (uid, ticket)
        return {"ok": True, "ticket": ticket_id}

    async def unlock(self, request: Mapping[str, Any]) -> dict[str, Any]:
        script_id = request.get("script_id")
        uid, ticket = self._tickets.pop(str(request.get("ticket")))
        if uid != str(uuid.UUID(str(script_id))):
            raise ValueError("导入锁票据与托管不符")
        await self._host().ScriptConfig[uuid.UUID(uid)].unlock(ticket)
        return {"ok": True}

    async def write(self, request: Mapping[str, Any]) -> dict[str, Any]:
        script_id = request.get("script_id")
        patch = request.get("patch") or {}
        ticket = request.get("ticket")
        data = _patch_dict_data(patch)
        if ticket is not None:
            # 调用方持着这个托管的 X 票：直接提交原节点；Config.update_script 的外部编辑入口
            # 会拒绝一切已锁节点，不能用于持票的内部写回。
            uid, _ticket = self._tickets[str(ticket)]
            if uid != str(uuid.UUID(str(script_id))):
                raise ValueError("导入锁票据与托管不符")
            config = self._host().ScriptConfig[uuid.UUID(uid)]
            await config.update(type(config).model_validate(data))
            return _write_result(True)
        found = self._lookup(script_id)
        if isinstance(found, _Miss):
            if found.status == "missing":
                return _write_result(False, "not_found", found.detail)
            return _write_result(False, "rejected", found.detail or "托管不归这个属主")
        try:
            # 托管 id 原样交给宿主（它会记进日志）
            await self._host().update_script(str(script_id), data)
        except RuntimeError as exc:
            return _write_result(False, "rejected", str(exc))
        except KeyError as exc:
            return _write_result(False, "not_found", str(exc))
        return _write_result(True)


class _Miss:
    """:meth:`ConfigOwner._lookup` 没找到：``status`` 与原话。"""

    __slots__ = ("status", "detail")

    def __init__(self, status: str, detail: str) -> None:
        self.status = status
        self.detail = detail


async def write_or_raise(
    owner: ConfigOwner,
    script_id: str,
    patch: Mapping[str, Any],
    *,
    ticket: str | None = None,
) -> None:
    """专项写回本托管的项目记录（经本插件自己的属主本地写，不绕道项目服务），没写成就抛。

    取代项目更新的 ``write_managed_record``：被拒是 ``RuntimeError``、没有这个托管是
    :class:`OwnerKeyError`，异常类型与文字和原先一样。``patch`` 的键见 :data:`RECORD_PATCH_KEYS`，
    键不在 = 不写。
    """

    request: dict[str, Any] = {"script_id": str(script_id), "patch": dict(patch)}
    if ticket is not None:
        request["ticket"] = ticket
    result = await owner.write(request)
    if result.get("ok"):
        return
    detail = str(result.get("detail") or "")
    if result.get("reason") == "not_found":
        raise OwnerKeyError(detail)
    raise RuntimeError(detail)


class OwnerServiceMixin:
    """混进专项的 ``Plugin``，把属主服务的 8 个操作接到 :class:`ConfigOwner` 上。

    子类给 ``owner_entry``（模块级那份 :class:`ConfigOwner`），``provides_services`` 并上
    ``owner_provides(<插件 id>)``。``list`` / ``read`` / ``check_source_path`` / ``plan_rules`` /
    ``project_mismatch`` 是同步的（项目服务在工作线程里调），``lock`` / ``unlock`` / ``write`` 是异步的。
    """

    owner_entry: ConfigOwner

    def owner_list(self, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self.owner_entry.list(request or {})

    def owner_read(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.owner_entry.read(request)

    def owner_check_source_path(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.owner_entry.check_source_path(request)

    def owner_plan_rules(
        self, request: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        return self.owner_entry.plan_rules_dict(request or {})

    def owner_project_mismatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.owner_entry.project_mismatch_message(request)

    async def owner_lock(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return await self.owner_entry.lock(request)

    async def owner_unlock(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return await self.owner_entry.unlock(request)

    async def owner_write(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return await self.owner_entry.write(request)


__all__ = [
    "OWNER_OPERATIONS",
    "OWNER_PROTOCOL",
    "OWNER_SERVICE_PREFIX",
    "RECORD_PATCH_KEYS",
    "ConfigOwner",
    "OwnerKeyError",
    "OwnerServiceMixin",
    "owner_provides",
    "owner_service_prefix",
    "record_payload",
    "write_or_raise",
]

