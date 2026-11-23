#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   SPDX-License-Identifier: AGPL-3.0-or-later

"""项目（``maafw.project.v1.*``，33 个）与项目更新（``maafw.project_update.v1.*``，13 个）服务操作，混进插件类。

契约见 MFW 服务化实施方案 §3.3（细节照同目录 ``契约-maafw_project_update.md``）。这里只是包装：打开、
更新、环境确认、收尾、预下载、发现都在作业里各建一份 ``MaaFWProjectSession`` 照原样跑，预约、修复、
复制 / 删除托管、补视图都转调原有的函数；那些类与函数原样保留，旧调用方照旧能直接用。

- 请求先经 ``contract.py`` 校验；多出来的键只按键名记 debug，请求本身一律不进日志（里面有托管级代理
  与 Mirror 酱 CDK）。托管记录（``record``）在 ``owners.ManagedRecord.from_payload`` 一处还原。
- 长操作用解析库 ``service_calls.HandleTable``：作业任务在 ``*_start`` 这次调用里 ``asyncio.create_task``
  建（读得到调用方的 ``current_process_scope``），不能用 ``background_tasks.spawn``。
- 打开作业持着视图预约：``open_release`` 交回（作业没完就挂到它完成上）；没 ``open_release`` 就
  ``open_close`` / 过期 / 停用时也会交回，不漏。修复作业的句柄由 ``run_release(after_job=…)`` 消费。

本模块顶层不导入 SDK：插件类在宿主里才建。
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Mapping
from typing import Any

from maafw_interface.service_calls import HandleTable, ServiceJob, exception_result

from .. import contract

#: 提供方被重载 / 停用后旧句柄的固定话（实施方案 §1 第 12 条）。
UNKNOWN_HANDLE_MESSAGE = "MFW 项目插件已重新加载或停用，本次项目操作的结果拿不到了"
#: 退出时（``on_teardown``）最多等多久：Runtime 关机只给后端约 5 秒。
TEARDOWN_WAIT_SECONDS = 2.0
#: 各族被停后调用方最多再等多久（``project_session`` 里原有的宽限，实施方案 §3.0）。
STOP_GRACE: dict[str, float | None] = {
    "open": 2.0,
    "confirm": 2.0,
    "repair": 0.0,
    "update": 60.0,
    "prefetch": 5.0,
    "discover": 5.0,
    "finish": None,
    "view_ensure": None,
    "script_cloned": None,
    "script_removed": None,
}
#: 预下载候选（``prefetch_token``）最长留多久：单次使用，24 h 只为防泄漏。
PREFETCH_TOKEN_TTL_SECONDS = 24 * 3600.0
#: 停用 / 重载时在途作业的拦截原因（新文案，只在手动停用、重载本插件时出现）。
BLOCKER_JOBS = (
    "MFW 有 {count} 项项目操作正在进行（打开、更新、确认环境、修复、复制或删除托管），"
    "请等它们结束后再操作"
)
OPEN_VIEW_MISSING = "请设置包含 interface.json 的 MFW 项目目录"
VIEW_ENSURE_BUSY = "该 MFW 托管正在运行或更新，稍后再试"
VIEW_ENSURE_NO_PATH = "请先设置 MFW 项目路径"


def _logger() -> Any:
    from auto_mas_core.host.utils import get_logger

    return get_logger("MFW 项目服务")


def _failure(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"ok": False, "code": code, "message": message, "detail": detail}


def _skipped(reason: str, message: str) -> dict[str, Any]:
    return {"ok": True, "outcome": "skipped", "reason": reason, "message": message}


def _notice(notice: Any) -> dict[str, Any] | None:
    if notice is None:
        return None
    return {"level": str(notice.level), "message": str(notice.message)}


def _record_update(record: Any) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "report": dict(record.report),
        "source_version": str(record.source_version),
        "imported_at": str(record.imported_at),
    }


def _seconds(instant: Any) -> float:
    """请求里的时刻（ISO 8601，契约已解析成 datetime）还原成会话要的秒数（``time.time()`` 口径）；
    没带就是 0（会话请求的缺省）。"""

    return 0.0 if instant is None else instant.timestamp()


def display_name(script_id: str) -> str:
    """``latest.by`` / ``switchedBy`` 记的托管 → 名字（经属主登记查），取不到时与专项原先的兜底链相同。"""

    from . import owners

    name = owners.display_name(str(script_id))
    if name is None:
        return "迁移" if str(script_id) == "迁移" else str(script_id)[:8] or "未知"
    return name or str(script_id)[:8]


def _current_scope() -> Any:
    from auto_mas_core.host.utils_common_process_scope import current_process_scope

    return current_process_scope.get()


class ProjectServices:
    """项目与项目更新服务操作；插件类混进它（``plugin.py``），也可以单独构造做测试。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._handles = HandleTable(
            unknown_handle_message=UNKNOWN_HANDLE_MESSAGE,
            on_discard=self._on_discard,
        )
        #: 打开作业的句柄 → 它拿的视图预约（交回后删）。
        self._open_keys: dict[str, str] = {}
        #: 预下载候选：token → (项目身份, (下载时的项目版本, 发现结果), 建立时刻)。
        self._prefetched: dict[str, tuple[Any, Any, float]] = {}
        #: 新形属主登记：(属主名, 服务名前缀) → 取入口的函数（同一属主重复登记交回同一个，owners 认 is）。
        self._owner_prefixes: dict[tuple[str, str], Callable[[], Any]] = {}

    # ------------------------------------------------------------------
    # 公共小件
    # ------------------------------------------------------------------

    def _parse(self, service: str, request: Any) -> tuple[Any, dict[str, Any] | None]:
        parsed, failure, extra = contract.parse_request(service, request)
        if extra:
            _logger().debug(f"{service} 请求里有不认识的键，已忽略：{', '.join(extra)}")
        return parsed, failure

    @staticmethod
    def _record(payload: contract.ManagedRecordPayload) -> Any:
        from .owners import ManagedRecord

        return ManagedRecord.from_payload(contract.record_dict(payload))

    def _session(self, job: ServiceJob, script_id: str) -> Any:
        """作业里的一份项目会话：事件进作业的队列，同组候选与查名都经属主登记现取。"""

        from . import owners
        from .project_session import (
            MaaFWProjectDownload,
            MaaFWProjectLog,
            MaaFWProjectPoint,
            MaaFWProjectSession,
        )

        def emit(event: Any) -> None:
            if isinstance(event, MaaFWProjectLog):
                job.emit("log", message=str(event.message), warning=False)
            elif isinstance(event, MaaFWProjectPoint):
                job.emit(
                    "point",
                    stage=str(event.stage),
                    state=str(event.state),
                    key=str(event.key),
                )
            elif isinstance(event, MaaFWProjectDownload):
                job.emit(
                    "download",
                    received=int(event.downloaded),
                    total=int(event.total),
                )

        return MaaFWProjectSession(
            emit,
            members=lambda: owners.group_members(exclude=script_id),
            display_name=display_name,
        )

    @staticmethod
    def _request(
        record: Any, *, owner: str, script_name: str = "", **extra: Any
    ) -> Any:
        from .project_session import project_request_from_record

        return project_request_from_record(
            record, owner=owner, script_name=script_name, **extra
        )

    async def _start(
        self,
        family: str,
        job_fn: Callable[[ServiceJob], Any],
        *,
        failure_code: str = "internal_error",
        cancelled_result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._sweep_prefetched()
        started = self._handles.start(
            family,
            job_fn,
            stop_grace=STOP_GRACE[family],
            failure_code=failure_code,
            cancelled_result=cancelled_result,
        )
        # 让作业任务先跑到第一个 await（登记好自己的停止回调）再把句柄交出去：任务还没开始就被
        # ``_stop`` 取消时，句柄表里的作业永远到不了终态，调用方会一直轮询下去。
        await asyncio.sleep(0)
        return started

    async def _poll(self, service: str, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(service, request)
        if failure is not None:
            return failure
        self._sweep_prefetched()
        return await self._handles.poll(family, request)

    def _stop(self, service: str, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(service, request)
        if failure is not None:
            return failure
        return self._handles.stop(family, request)

    def _close(self, service: str, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(service, request)
        if failure is not None:
            return failure
        return self._handles.close(family, request)

    def _on_discard(self, job: ServiceJob) -> None:
        """终态作业离开句柄表：打开作业没交回的预约交回。"""

        if job.family == "open":
            self._release_open_key(job.handle)

    def _release_open_key(self, handle: str) -> None:
        from .project_path import release_project_path_sync

        release_project_path_sync(self._open_keys.pop(handle, None))

    def _release_open_keys_when_done(self, jobs: list[ServiceJob]) -> None:
        """停用 / 退出清表时：打开作业的预约等作业做完再交回（工作线程还在改视图时不先放）。"""

        for job in jobs:
            if job.family != "open" or job.handle not in self._open_keys:
                continue
            task = job.task
            if task is None or task.done():
                self._release_open_key(job.handle)
            else:
                task.add_done_callback(
                    lambda _task, handle=job.handle: self._release_open_key(handle)
                )

    def _sweep_prefetched(self) -> None:
        now = time.monotonic()
        for token in [
            token
            for token, (_, _, created) in self._prefetched.items()
            if now - created >= PREFETCH_TOKEN_TTL_SECONDS
        ]:
            del self._prefetched[token]

    # ------------------------------------------------------------------
    # 版本、属主登记
    # ------------------------------------------------------------------

    async def project_version(self, request: Any = None) -> dict[str, Any]:
        _, failure = self._parse(f"{contract.PROJECT}.version", request)
        if failure is not None:
            return failure
        from ..plugin import PACKAGE_NAME, PACKAGE_VERSION

        return {"ok": True, "package": PACKAGE_NAME, "version": PACKAGE_VERSION}

    async def project_owner_register(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.owner_register", request)
        if failure is not None:
            return failure
        from . import owners
        from .owner_services import ServiceOwnerEntry

        name, prefix = parsed.name, parsed.prefix
        resolve = self._owner_prefixes.get((name, prefix))
        if resolve is None:
            entry = ServiceOwnerEntry(name, prefix, self.services)

            def resolve() -> Any:
                # 每次现取：属主的服务此刻没登记就交回 None，owners 当成「属主没登记」
                return entry if entry.available() else None

        try:
            owners.register_owner(name, resolve=resolve)
        except ValueError as exc:
            return _failure("owner_conflict", str(exc))
        self._owner_prefixes[(name, prefix)] = resolve
        schedule = getattr(self, "_schedule_rerun_after_owner", None)
        if callable(schedule):
            schedule()
        return {"ok": True}

    async def project_owner_unregister(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.owner_unregister", request)
        if failure is not None:
            return failure
        self._forget_owner(parsed.name)
        return {"ok": True}

    def _forget_owner(self, name: str) -> None:
        """撤掉属主登记（新旧两种登记一起撤）。"""

        from . import owners

        owners.unregister_owner(name)
        for key in [key for key in self._owner_prefixes if key[0] == name]:
            del self._owner_prefixes[key]
        resolvers = getattr(self, "_resolvers", None)
        if isinstance(resolvers, dict):
            for key in [key for key in resolvers if key[0] == name]:
                del resolvers[key]

    # ------------------------------------------------------------------
    # 短操作
    # ------------------------------------------------------------------

    async def project_managed_find(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.managed_find", request)
        if failure is not None:
            return failure
        from . import owners

        try:
            owner, record = owners.find_managed(parsed.script_id)
        except ValueError as exc:
            return _failure("invalid_id", str(exc))
        except owners.OwnerKeyError as exc:
            return _failure("not_found", str(exc))
        except TypeError as exc:
            return _failure("not_managed", str(exc))
        return {"ok": True, "owner": owner, "record": record.to_payload()}

    async def project_project_context(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.project_context", request)
        if failure is not None:
            return failure
        from .embedded_project import (
            embedded_project_dir,
            follow_source_enabled,
            is_source_form,
            shell_hint_from_report,
            view_imported_from,
        )
        from .update_credentials import (
            resolve_auto_update_mode,
            resolve_update_credentials,
            resolve_update_proxy_url,
        )

        record = self._record(parsed.record)
        shape = record.shape()
        imported_from: bool | None = None
        if parsed.with_view_import_check:
            # 要读载荷清单，放工作线程
            imported_from = await asyncio.to_thread(
                view_imported_from,
                record.uid,
                str(record.source_path or "").strip(),
            )
        return {
            "ok": True,
            "auto_update_mode": resolve_auto_update_mode(shape),
            "proxy_url": resolve_update_proxy_url(shape),
            "follow_source": follow_source_enabled(shape),
            "source_form": is_source_form(shape),
            "channel": resolve_update_credentials(shape).channel,
            "shell_hint": shell_hint_from_report(shape),
            "view_dir": str(embedded_project_dir(record.uid)),
            "view_imported_from_source": imported_from,
        }

    async def project_project_peek(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.project_peek", request)
        if failure is not None:
            return failure
        from .embedded_project import (
            embedded_project_dir,
            switch_or_confirm_in_progress,
        )
        from .project_path import is_project_path_reserved, is_project_updating
        from .project_session import peek_project_skip

        script_id = parsed.script_id
        view = embedded_project_dir(script_id)
        outcome = await asyncio.to_thread(peek_project_skip, script_id)
        switching = await asyncio.to_thread(switch_or_confirm_in_progress, script_id)
        return {
            "ok": True,
            "reserved": is_project_path_reserved(view),
            "updating": is_project_updating(view),
            "switching": bool(switching),
            "skip": (
                None
                if outcome is None
                else {"reason": str(outcome.skip), "message": str(outcome.reason)}
            ),
        }

    async def project_run_reserve(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.run_reserve", request)
        if failure is not None:
            return failure
        from .embedded_project import embedded_project_dir
        from .project_path import is_project_updating, try_reserve_project_path
        from .project_session import SKIP_OCCUPIED, SKIP_UPDATING

        view = embedded_project_dir(parsed.script_id)
        key = await try_reserve_project_path(view)
        if key is None:
            if is_project_updating(view):
                return _skipped("updating", SKIP_UPDATING)
            return _skipped("occupied", SKIP_OCCUPIED)
        return {"ok": True, "key": key}

    async def project_run_release(self, request: Any = None) -> dict[str, Any]:
        """交回账号运行的预约；``after_job`` 是还在跑的修复作业时挂到它完成上（同原
        ``project_path.release_run_reservation`` 等 ``pending`` 的那两条）。"""

        parsed, failure = self._parse(f"{contract.PROJECT}.run_release", request)
        if failure is not None:
            return failure
        from .project_path import _logger as release_logger
        from .project_path import release_project_path_sync

        key = parsed.key
        keep_on_error = parsed.on_job_error == "keep"
        job = (
            self._handles.get("repair", {"handle": parsed.after_job})
            if parsed.after_job
            else None
        )

        def settle(finished: ServiceJob) -> bool:
            result = finished.result or {}
            failed = not result.get("ok") and result.get("code") != "cancelled"
            if failed and keep_on_error:
                release_logger.warning(
                    f"MaaFW 项目核对未确认，保留占用: {result.get('message') or ''}"
                )
                return False
            release_project_path_sync(key)
            return True

        if job is None:
            release_project_path_sync(key)
            return {"ok": True, "released": True, "deferred": False}
        # 句柄被 run_release 消费：之后再拿它取事件就是 unknown_handle
        self._handles.close("repair", {"handle": job.handle})
        if job.finished:
            released = settle(job)
            return {"ok": True, "released": released, "deferred": False}
        task = job.task
        assert task is not None
        task.add_done_callback(lambda _task: settle(job))
        return {"ok": True, "released": False, "deferred": True}

    # ------------------------------------------------------------------
    # 打开项目
    # ------------------------------------------------------------------

    async def project_open_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.open_start", request)
        if failure is not None:
            return failure
        from .project_session import current_siblings

        record = self._record(parsed.record)
        holder: dict[str, ServiceJob] = {}
        session = self._session(_LazyJob(holder), parsed.script_id)
        skipped = await session.reserve(parsed.script_id)
        if skipped is not None:
            return _skipped(str(skipped.skip), str(skipped.reason))
        key = session._open_key
        # 同来源重建的候选在拿到预约这一刻现抄（与原先「组请求那一刻」同一时机）
        project_request = self._request(
            record,
            owner=parsed.owner,
            script_name=parsed.script_name,
            siblings=current_siblings(),
            round_started_at=_seconds(parsed.round_started_at),
        )
        scope = _current_scope()

        async def run(job: ServiceJob) -> dict[str, Any]:
            holder["job"] = job
            # 停止只置打开令牌：正在跑的那一步做完就返回「已停止」，不取消任务
            job.on_stop(lambda _reason: session._open_stop.set())
            return self._open_result(await session.prepare(project_request))

        started = await self._start(
            "open",
            run,
            failure_code="import_failed",
            cancelled_result={"ok": True, "outcome": "stopped", "record_update": None},
        )
        handle = started["handle"]
        if key is not None:
            self._open_keys[handle] = key
        # 预约归句柄（open_release / 收尾时交回），会话里不再拿着
        session._open_key = None
        job = self._handles.get("open", {"handle": handle})
        if scope is not None and job is not None and job.task is not None:
            # 补视图在工作线程里改视图：运行被取消时宿主等它收尾（原 ``hold`` 的 retain_worker）
            scope.retain_worker(job.task)
        return started

    @staticmethod
    def _open_result(outcome: Any) -> dict[str, Any]:
        record_update = _record_update(outcome.record)
        if outcome.kind == "opened":
            lease = outcome.lease
            return {
                "ok": True,
                "outcome": "opened",
                "lease": {
                    "view_path": str(lease.view_path),
                    "interface_path": str(lease.interface_path),
                    "version": str(lease.version),
                },
                "record_update": record_update,
                "env_confirm_needed": bool(outcome.env_confirm_needed),
            }
        if outcome.kind == "stopped":
            return {"ok": True, "outcome": "stopped", "record_update": record_update}
        code = (
            "view_missing" if outcome.reason == OPEN_VIEW_MISSING else "import_failed"
        )
        return _failure(
            code,
            str(outcome.reason),
            record_update=record_update,
            env_confirm_needed=bool(outcome.env_confirm_needed),
        )

    async def project_open_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(f"{contract.PROJECT}.open_poll", "open", request)

    async def project_open_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(f"{contract.PROJECT}.open_stop", "open", request)

    async def project_open_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(f"{contract.PROJECT}.open_close", "open", request)

    async def project_open_release(self, request: Any = None) -> dict[str, Any]:
        """交回打开作业拿的预约并丢掉句柄；作业还没完就挂到它完成上（原 ``_release_after_work``）。"""

        parsed, failure = self._parse(f"{contract.PROJECT}.open_release", request)
        if failure is not None:
            return failure
        job = self._handles.get("open", {"handle": parsed.handle})
        if job is None:
            return self._handles.unknown_handle()
        finished = job.finished
        if finished:
            self._release_open_key(job.handle)
        elif job.task is not None:
            job.task.add_done_callback(
                lambda _task, handle=job.handle: self._release_open_key(handle)
            )
        self._handles.close("open", {"handle": job.handle})
        return {"ok": True, "released": finished, "deferred": not finished}

    # ------------------------------------------------------------------
    # 运行环境确认、收尾
    # ------------------------------------------------------------------

    @staticmethod
    def _stop_handler(job: ServiceJob, session: Any) -> Callable[[str | None], None]:
        """``stop_requested``：收尾期间用户点了停止（会话 ``stop()``）；其余：取消作业任务（原先
        ``CancelledError`` 那一路）。"""

        def handler(reason: str | None) -> None:
            if reason == "stop_requested":
                session.stop()
            elif job.task is not None:
                job.task.cancel()

        return handler

    async def project_confirm_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.confirm_start", request)
        if failure is not None:
            return failure
        record = self._record(parsed.record)

        async def run(job: ServiceJob) -> dict[str, Any]:
            session = self._session(job, parsed.script_id)
            job.on_stop(self._stop_handler(job, session))
            if parsed.stop_requested:
                session.stop()
            notice = await session.confirm_environment(
                self._request(record, owner=parsed.owner), parsed.phase
            )
            return {"ok": True, "outcome": session.outcome, "notice": _notice(notice)}

        return await self._start(
            "confirm",
            run,
            cancelled_result={"ok": True, "outcome": "stopped", "notice": None},
        )

    async def project_confirm_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(f"{contract.PROJECT}.confirm_poll", "confirm", request)

    async def project_confirm_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(f"{contract.PROJECT}.confirm_stop", "confirm", request)

    async def project_confirm_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(f"{contract.PROJECT}.confirm_close", "confirm", request)

    async def project_finish_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.finish_start", request)
        if failure is not None:
            return failure
        record = self._record(parsed.record)

        async def run(job: ServiceJob) -> dict[str, Any]:
            session = self._session(job, parsed.script_id)
            # 收尾没有停止点：退出时的「置停止」不取消它
            job.on_stop(lambda _reason: None)
            outcome = await session.close(
                self._request(
                    record,
                    owner=parsed.owner,
                    script_name=parsed.script_name,
                    round_started_at=parsed.round_started_at,
                ),
                sync_group=parsed.sync_group,
            )
            return {"ok": True, "env_confirm_needed": bool(outcome.env_confirm_needed)}

        return await self._start("finish", run)

    async def project_finish_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(f"{contract.PROJECT}.finish_poll", "finish", request)

    async def project_finish_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(f"{contract.PROJECT}.finish_close", "finish", request)

    # ------------------------------------------------------------------
    # 资源包修复
    # ------------------------------------------------------------------

    async def project_repair_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.repair_start", request)
        if failure is not None:
            return failure
        record = self._record(parsed.record)
        scope = _current_scope()

        async def run(job: ServiceJob) -> dict[str, Any]:
            return await self._repair_job(job, parsed, record)

        started = await self._start(
            "repair",
            run,
            cancelled_result={"ok": True, "checked_now": True, "rerun": None},
        )
        job = self._handles.get("repair", started) if started.get("ok") else None
        retain = getattr(scope, "retain_worker", None)
        if job is not None and job.task is not None and callable(retain):
            # 用户停止后作业交给 run_release 等（核对照样跑完）：宿主收尾会取消作用域上下文里没登记成
            # 保留任务的任务，作业要活过这一步（原来等核对的那个后台任务也是保留任务）
            retain(job.task)
        return started

    async def _repair_job(
        self, job: ServiceJob, parsed: Any, record: Any
    ) -> dict[str, Any]:
        from .embedded_project import follow_source_enabled, shell_hint_from_report
        from .resource_repair import MaaFWRepairRequest, MaaFWResourceRepair
        from .update_credentials import (
            resolve_update_credentials,
            resolve_update_proxy_url,
        )

        shape = record.shape()
        repair_request = MaaFWRepairRequest(
            script_id=parsed.script_id,
            script_name=parsed.script_name,
            follow_source=follow_source_enabled(shape),
            channel=resolve_update_credentials(shape).channel,
            proxy_url=resolve_update_proxy_url(shape),
            shell_hint=shell_hint_from_report(shape),
        )

        def log(message: Any, *, warning: bool = False) -> None:
            job.emit("log", message=str(message), warning=bool(warning))

        repair = MaaFWResourceRepair(log)
        repair.checked = bool(parsed.already_checked)
        runner = asyncio.ensure_future(repair.run(parsed.kind, repair_request))
        # 停止只让核对停下（原先调用方被取消时置停止令牌），核对任务照样跑完：取消 ``run``，它在
        # ``except CancelledError`` 里置令牌再上抛，核对任务本身经 ``asyncio.shield`` 跑完。
        job.on_stop(lambda _reason: runner.cancel())
        rerun = None
        try:
            rerun = await asyncio.shield(runner)
        except asyncio.CancelledError:
            if not runner.done():
                # 作业本身被取消（停用）：核对一并停
                runner.cancel()
                raise
        if runner.cancelled() and repair.task is not None:
            # 停下之后等核对任务收尾（释放预约要等它，``run_release(after_job=…)``）；它出错就让
            # 结果是失败（交回时按 ``on_job_error`` 决定留不留占用）
            await repair.task
        return {
            "ok": True,
            "checked_now": bool(repair.checked and not parsed.already_checked),
            "rerun": None if rerun is None else {"line": rerun[0], "title": rerun[1]},
        }

    async def project_repair_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(f"{contract.PROJECT}.repair_poll", "repair", request)

    async def project_repair_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(f"{contract.PROJECT}.repair_stop", "repair", request)

    async def project_repair_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(f"{contract.PROJECT}.repair_close", "repair", request)

    # ------------------------------------------------------------------
    # 补视图（外壳导入的有效根）
    # ------------------------------------------------------------------

    async def project_view_ensure_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(f"{contract.PROJECT}.view_ensure_start", request)
        if failure is not None:
            return failure

        async def run(job: ServiceJob) -> dict[str, Any]:
            from ..api.common import maafw_effective_root

            job.on_stop(lambda _reason: None)
            root, error = await maafw_effective_root(
                parsed.script_id, parsed.fallback_path
            )
            if root is not None:
                return {"ok": True, "root": str(root)}
            if not parsed.script_id:
                code = "no_path"
            elif error.startswith("MFW 脚本无效"):
                code = "invalid_managed"
            elif error == VIEW_ENSURE_BUSY:
                code = "busy"
            else:
                code = "import_failed"
            return _failure(code, error)

        return await self._start("view_ensure", run)

    async def project_view_ensure_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT}.view_ensure_poll", "view_ensure", request
        )

    async def project_view_ensure_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(
            f"{contract.PROJECT}.view_ensure_close", "view_ensure", request
        )

    # ------------------------------------------------------------------
    # 复制、删除托管
    # ------------------------------------------------------------------

    async def project_script_cloned_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT}.script_cloned_start", request
        )
        if failure is not None:
            return failure
        source_record = self._record(parsed.source_record)

        async def run(job: ServiceJob) -> dict[str, Any]:
            from .embedded_project import (
                FollowSourceCloneUnavailable,
                clone_embedded_copy,
                embedded_project_dir,
                is_source_form,
            )
            from .project_path import release_project_path, try_reserve_project_path

            job.on_stop(lambda _reason: None)
            # 目标托管的 FollowSource=False 由调用方在调用前自己写（那是专项的配置）
            group_channel = str(source_record.channel or "stable")
            source_form = is_source_form(source_record.shape())
            target_key = await try_reserve_project_path(
                embedded_project_dir(parsed.target_id)
            )
            if target_key is None:
                return _skipped("occupied", "")
            try:
                await asyncio.to_thread(
                    lambda: clone_embedded_copy(
                        source_script_id=parsed.source_id,
                        target_script_id=parsed.target_id,
                        group_channel=group_channel,
                        source_form=source_form,
                        owner=parsed.owner,
                    )
                )
            except FollowSourceCloneUnavailable as exc:
                return _skipped("follow_source_clone_unavailable", str(exc))
            except Exception as exc:  # noqa: BLE001 - 失败下次运行会按来源 / 载荷重建
                return exception_result("clone_failed", exc)
            finally:
                await release_project_path(target_key)
            return {"ok": True, "outcome": "cloned"}

        return await self._start("script_cloned", run)

    async def project_script_cloned_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT}.script_cloned_poll", "script_cloned", request
        )

    async def project_script_cloned_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(
            f"{contract.PROJECT}.script_cloned_close", "script_cloned", request
        )

    async def project_script_removed_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT}.script_removed_start", request
        )
        if failure is not None:
            return failure

        async def run(job: ServiceJob) -> dict[str, Any]:
            from .embedded_project import embedded_project_dir, remove_tree, view_owner
            from .live_projects import reconcile_in_background

            job.on_stop(lambda _reason: None)
            view = embedded_project_dir(parsed.script_id)
            outcome = "absent"
            recorded_owner: str | None = None
            if view.exists():
                recorded = await asyncio.to_thread(view_owner, view)
                recorded_owner = None if recorded is None else recorded[0]
                if recorded is not None and recorded[0] != parsed.owner:
                    outcome = "kept_other_owner"
                else:
                    await asyncio.to_thread(remove_tree, view)
                    outcome = "removed"
            # 先删后对账（``script_lifecycle`` 的口径）：对账在后台跑，不拖慢删除
            reconcile_in_background("script-deleted")
            return {
                "ok": True,
                "outcome": outcome,
                "recorded_owner": recorded_owner,
                "view_path": str(view),
            }

        return await self._start("script_removed", run)

    async def project_script_removed_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT}.script_removed_poll", "script_removed", request
        )

    async def project_script_removed_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(
            f"{contract.PROJECT}.script_removed_close", "script_removed", request
        )

    # ------------------------------------------------------------------
    # 项目更新：更新、预下载、发现
    # ------------------------------------------------------------------

    async def project_update_update_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT_UPDATE}.update_start", request
        )
        if failure is not None:
            return failure
        record = self._record(parsed.record)
        prefetched = (
            self._prefetched.pop(parsed.prefetch_token, None)
            if parsed.prefetch_token
            else None
        )

        async def run(job: ServiceJob) -> dict[str, Any]:
            session = self._session(job, parsed.script_id)
            if prefetched is not None:
                # 预下载的候选（单次使用）交回会话：更新在谱系锁内按项目身份核对后用
                identity, update, _created = prefetched
                session._prefetched_project_identity = identity
                session._prefetched_project_update = update
            job.on_stop(self._stop_handler(job, session))
            if parsed.stop_requested:
                session.stop()
            notice = await session.update(
                self._request(
                    record,
                    owner=parsed.owner,
                    script_name=parsed.script_name,
                    params={"prefetch_paths": dict(parsed.prefetch_paths)},
                ),
                parsed.phase,
            )
            return {"ok": True, "outcome": session.outcome, "notice": _notice(notice)}

        return await self._start(
            "update",
            run,
            cancelled_result={"ok": True, "outcome": "stopped", "notice": None},
        )

    async def project_update_update_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT_UPDATE}.update_poll", "update", request
        )

    async def project_update_update_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(f"{contract.PROJECT_UPDATE}.update_stop", "update", request)

    async def project_update_update_close(self, request: Any = None) -> dict[str, Any]:
        return self._close(f"{contract.PROJECT_UPDATE}.update_close", "update", request)

    async def project_update_prefetch_start(
        self, request: Any = None
    ) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT_UPDATE}.prefetch_start", request
        )
        if failure is not None:
            return failure
        record = self._record(parsed.record)

        async def run(job: ServiceJob) -> dict[str, Any]:
            session = self._session(job, parsed.script_id)
            await session.prefetch(self._request(record, owner=parsed.owner))
            if session._prefetched_project_update is None:
                return _skipped(session.prefetch_skip_reason or "no_candidate", "")
            token = secrets.token_hex(16)
            self._prefetched[token] = (
                session._prefetched_project_identity,
                session._prefetched_project_update,
                time.monotonic(),
            )
            return {"ok": True, "outcome": "downloaded", "token": token}

        return await self._start("prefetch", run, failure_code="prefetch_failed")

    async def project_update_prefetch_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT_UPDATE}.prefetch_poll", "prefetch", request
        )

    async def project_update_prefetch_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(
            f"{contract.PROJECT_UPDATE}.prefetch_stop", "prefetch", request
        )

    async def project_update_prefetch_close(
        self, request: Any = None
    ) -> dict[str, Any]:
        return self._close(
            f"{contract.PROJECT_UPDATE}.prefetch_close", "prefetch", request
        )

    async def project_update_prefetch_discard(
        self, request: Any = None
    ) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT_UPDATE}.prefetch_discard", request
        )
        if failure is not None:
            return failure
        self._prefetched.pop(parsed.token, None)
        return {"ok": True}

    async def project_update_discover_start(
        self, request: Any = None
    ) -> dict[str, Any]:
        parsed, failure = self._parse(
            f"{contract.PROJECT_UPDATE}.discover_start", request
        )
        if failure is not None:
            return failure
        record = self._record(parsed.record)

        async def run(job: ServiceJob) -> dict[str, Any]:
            from .project_session import discover_prefetch

            downloads = await discover_prefetch(
                self._request(record, owner=parsed.owner)
            )
            return {
                "ok": True,
                "downloads": [
                    {
                        "url": str(item.url),
                        "rid": item.rid,
                        "content_hash": item.content_hash,
                        "downloader": item.downloader,
                    }
                    for item in downloads
                ],
            }

        return await self._start("discover", run, failure_code="discover_failed")

    async def project_update_discover_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll(
            f"{contract.PROJECT_UPDATE}.discover_poll", "discover", request
        )

    async def project_update_discover_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop(
            f"{contract.PROJECT_UPDATE}.discover_stop", "discover", request
        )

    async def project_update_discover_close(
        self, request: Any = None
    ) -> dict[str, Any]:
        return self._close(
            f"{contract.PROJECT_UPDATE}.discover_close", "discover", request
        )

    # ------------------------------------------------------------------
    # 停用、退出
    # ------------------------------------------------------------------

    def service_blockers(self) -> list[str]:
        """``teardown_blockers`` 加的那一句：只读内存表，不等。"""

        running = [
            job for job in self._handles.jobs() if not job.finished and not job.detached
        ]
        if not running:
            return []
        return [BLOCKER_JOBS.format(count=len(running))]

    async def shutdown_services(self, *, teardown: bool) -> None:
        """停用（``teardown=False``）或退出（``teardown=True``）时收掉句柄表。

        - 停用：对在途作业置停止、取消作业任务；打开作业的预约等作业做完再交回；清空句柄表与预下载候选。
        - 退出：对在途作业置停止，最多等 2 秒，然后清表；预约同上。
        """

        jobs = self._handles.jobs()
        if teardown:
            await self._handles.shutdown(TEARDOWN_WAIT_SECONDS, "teardown")
        else:
            self._handles.abort_all("disable")
        self._release_open_keys_when_done(jobs)
        self._prefetched.clear()


class _LazyJob:
    """打开作业在 ``_start`` 里先建会话（拿预约），作业建好后才有 ``ServiceJob``：事件转给它。"""

    def __init__(self, holder: dict[str, ServiceJob]) -> None:
        self._holder = holder

    def emit(self, type: str, **fields: Any) -> None:
        job = self._holder.get("job")
        if job is not None:
            job.emit(type, **fields)


#: 服务名 → 本类上的方法名（``plugin.provides_services`` 用）。
SERVICE_METHODS: dict[str, str] = {
    name: contract.method_name(name) for name in contract.SERVICE_NAMES
}


__all__ = [
    "BLOCKER_JOBS",
    "PREFETCH_TOKEN_TTL_SECONDS",
    "SERVICE_METHODS",
    "STOP_GRACE",
    "TEARDOWN_WAIT_SECONDS",
    "UNKNOWN_HANDLE_MESSAGE",
    "ProjectServices",
    "display_name",
]
