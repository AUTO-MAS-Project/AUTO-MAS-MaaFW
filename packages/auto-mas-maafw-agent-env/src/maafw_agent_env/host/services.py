"""agent 环境的 22 个服务操作（``maafw.agent_env.v1.<操作>``），混进插件类。

契约见 MFW 服务化实施方案 §3.1（细节照同目录 ``契约-maafw_agent_env.md``）。这里只是包装：
借环境、准备环境、预检、回收、缓存都转调本包原有的函数，那些函数原样保留，旧调用方照旧能直接导入。

- 请求先经 ``contract.py`` 校验；多出来的键只按键名记 debug，不记值，请求本身一律不进日志
  （里面有代理凭据）。
- 长操作用解析库 ``service_calls.HandleTable``：作业任务在 ``*_start`` 这次调用里
  ``asyncio.create_task`` 建（读得到调用方的 ``current_process_scope``），不能用
  ``background_tasks.spawn``（它换成脱离作用域的上下文）。
- 借到的租约：调用方经 ``borrow_poll`` 取走结果之前，提供方负责还——``_stop`` 之后恰好借成、
  ``_close`` 脱手后借成、终态 10 分钟没人取、停用 / 退出时都还掉。取走之后由调用方 ``borrow_return``。

本模块顶层不导入 SDK 与运行池：插件类在宿主里才建，测试也能不带宿主导入它。会拉起运行池的模块
只在事件循环上（服务方法体里）导入，交给工作线程的是导入好的函数——几个工作线程并发冷导入同一个包
会在导入锁上死锁。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from maafw_interface.service_calls import (
    HandleTable,
    ServiceJob,
    exception_result,
)

from .. import contract
from ._logging import get_logger

logger = get_logger("MFW agent 环境")
# 编辑页准备后的提示性导入检查沿用端点原来的 logger 名。
_env_logger = get_logger("MFW 运行环境")
# 后台回收失败那句沿用原来的 logger 名（``live_projects.reconcile_in_background``）。
_reconcile_logger = get_logger("MFW 运行池回收")

#: 提供方被重载 / 停用后旧句柄的固定话（实施方案 §1 第 12 条）。
UNKNOWN_HANDLE_MESSAGE = (
    "MFW agent 环境插件已重新加载或停用，本次环境准备的结果拿不到了"
)
#: 退出时（``on_teardown``）最多等多久：Runtime 关机只给后端约 5 秒。
TEARDOWN_WAIT_SECONDS = 2.0
#: ``borrow`` / ``prepare`` 被取消后调用方的宽限（运行 ``_PREPARE_ENVIRONMENT_CANCEL_GRACE_SECONDS``、
#: 项目 ``_ENV_PREPARE_CANCEL_GRACE_SECONDS`` 都是 2 秒）；``trial`` 等到结束，``reconcile`` 没有 ``_stop``。
STOP_GRACE = {"borrow": 2.0, "prepare": 2.0, "trial": None, "reconcile": None}

#: 借环境被停下（或作业被取消）时的原文，同 ``runtime_lease._raise_if_prepare_cancelled``。
BORROW_CANCELLED_MESSAGE = "MaaFW Runner 环境准备已取消"
ENV_CANCELLED_MESSAGE = "MaaFW 运行环境准备已取消"
#: 回收这一轮弃权（另一轮在跑、池目录不在、有项目不可达……），原因已由回收自己写进日志。
RECONCILE_ABSTAINED_MESSAGE = "运行池回收本轮弃权，原因见后端日志"
#: 报错照跑放行时那句日志（``project_environment.prepare_project_environment_sync``）。
LENIENT_PASS_LOG = "运行环境检查没通过、按「报错照跑」放行，这次不记为「运行环境已就绪」，下次运行前再查"

BLOCKER_PREPARING = (
    "MFW agent 环境还有 {count} 个运行环境准备没有结束，请等它们结束后再操作"
)
BLOCKER_RECONCILING = "MFW 运行池回收正在进行，请稍后再操作"
BLOCKER_LEASES = "MFW 有 {count} 个运行正在使用运行环境"


def _stopped(message: str, **detail: Any) -> dict[str, Any]:
    return {"ok": False, "code": "stopped", "message": message, "detail": detail}


def _jsonable(value: Any) -> Any:
    """回收报告 / 释放结果转成只含 JSON 值的结构（路径转字符串、元组集合转列表）。"""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _ignore_stop_reason(_reason: str | None) -> None:
    """``_stop`` 只置停止令牌（``job.stop_event``），不取消作业任务：令牌传进安装线程，
    正在跑的 uv / pip 子进程随之终止，作业照常走到结果。"""


def _worker_paths() -> list[str]:
    """worker 要导入本包时的导入路径：本包所在的父目录（按自己的 ``__file__`` 算）。"""

    import maafw_agent_env

    return [str(Path(maafw_agent_env.__file__).resolve().parent.parent)]


def _current_scope() -> Any:
    """调用方的进程作用域（在服务方法体里调，读的是调用方的上下文）。"""

    from auto_mas_core.host.utils_common_process_scope import current_process_scope

    return current_process_scope.get()


class AgentEnvServices:
    """agent 环境服务操作；插件类混进它（``plugin.py``），也可以单独构造做测试。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._handles = HandleTable(
            unknown_handle_message=UNKNOWN_HANDLE_MESSAGE,
            on_discard=self._on_discard,
        )
        #: 已经交给调用方、还没还的租约：(runtime_id, lease_id) → 记录。
        self._leases: dict[tuple[str, str], dict[str, Any]] = {}
        #: 提供方自己还租约的后台任务（退出时在 2 秒里一起等）。
        self._cleanups: set[asyncio.Task[Any]] = set()
        #: 已经由提供方负责还过（或交出去）的借环境作业，不重复还。
        self._settled: set[str] = set()
        #: 借环境句柄 → 请求里的租约有效期（结果交出去时记进 ``_leases``）。
        self._borrow_ttl: dict[str, float | None] = {}

    # ------------------------------------------------------------------
    # 公共小件
    # ------------------------------------------------------------------

    def _parse(self, op: str, request: Any) -> tuple[Any, dict[str, Any] | None]:
        parsed, failure, extra = contract.parse_request(op, request)
        if extra:
            logger.debug(f"{op} 请求里有不认识的键，已忽略：{', '.join(extra)}")
        return parsed, failure

    def _spawn_cleanup(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._cleanups.add(task)

        def _done(done: asyncio.Task[Any]) -> None:
            self._cleanups.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.warning(f"MFW agent 环境还运行环境租约失败: {exc}")

        task.add_done_callback(_done)
        return task

    @staticmethod
    def _emit_log(job: ServiceJob) -> Callable[[str], None]:
        def send_log(message: str) -> None:
            job.emit_threadsafe("log", message=str(message), warning=False)

        return send_log

    @staticmethod
    def _emit_progress(job: ServiceJob) -> Callable[[dict[str, Any]], None]:
        def progress(event: dict[str, Any]) -> None:
            job.emit_threadsafe("progress", data=_jsonable(dict(event)))

        return progress

    async def _run_worker(
        self,
        operation: Callable[[], Any],
        scope: Any,
        *,
        cancel: Callable[[], None],
        release_cancelled: Callable[[Any], Any] | None = None,
    ) -> Any:
        """在工作线程里跑 ``operation``。

        有调用方的进程作用域时经 ``scope.run_update_worker``（与原先 ``plan_run`` 同一做法：
        作用域停止时取消本作业，迟到的成功交给 ``release_cancelled``）；没有时自己照同样的
        规则跑：被取消就置令牌，迟到的成功在后台交给 ``release_cancelled``。
        """

        if scope is not None:
            return await scope.run_update_worker(
                operation, cancel=cancel, release_cancelled=release_cancelled
            )
        worker = asyncio.ensure_future(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel()

            def _late(done: asyncio.Future[Any]) -> None:
                if done.cancelled() or done.exception() is not None:
                    return
                if release_cancelled is not None:
                    self._spawn_cleanup(
                        asyncio.to_thread(release_cancelled, done.result())
                    )

            worker.add_done_callback(_late)
            raise

    # ------------------------------------------------------------------
    # 租约：提供方负责还的那部分
    # ------------------------------------------------------------------

    @staticmethod
    def _lease_fields(result: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "runtime_pool_root": result.get("runtime_pool_root"),
            "runtime_id": result.get("runtime_id"),
            "lease_id": result.get("lease_id"),
            "binding_version": result.get("binding_version"),
        }

    def _return_lease_later(self, fields: Mapping[str, Any]) -> None:
        from ..core.agent_env.runtime_lease import return_runtime_environment

        self._spawn_cleanup(asyncio.to_thread(return_runtime_environment, **fields))

    def _settle_borrow(self, job: ServiceJob) -> None:
        """借环境作业的结果没被调用方取走：提供方把租约还掉（只还一次）。"""

        if job.family != "borrow" or job.handle in self._settled:
            return
        result = job.result
        if not (isinstance(result, Mapping) and result.get("ok") is True):
            return
        if job.result_taken:
            return
        self._settled.add(job.handle)
        self._return_lease_later(self._lease_fields(result))

    def _on_discard(self, job: ServiceJob) -> None:
        self._settle_borrow(job)
        self._settled.discard(job.handle)
        self._borrow_ttl.pop(job.handle, None)

    def _record_handed_out(self, result: Mapping[str, Any], ttl: float | None) -> None:
        runtime_id = str(result.get("runtime_id") or "")
        lease_id = str(result.get("lease_id") or "")
        if not runtime_id or not lease_id:
            return
        self._leases.setdefault(
            (runtime_id, lease_id),
            {
                **self._lease_fields(result),
                "expires_at": None if ttl is None else time.monotonic() + float(ttl),
            },
        )

    def _outstanding_leases(self) -> int:
        now = time.monotonic()
        return sum(
            1
            for item in self._leases.values()
            if item["expires_at"] is None or item["expires_at"] > now
        )

    # ------------------------------------------------------------------
    # 普通操作
    # ------------------------------------------------------------------

    async def version(self, request: Any = None) -> dict[str, Any]:
        _, failure = self._parse("version", request)
        if failure is not None:
            return failure
        from ..core.worker_api import WORKER_API_VERSIONS
        from ..plugin import DISTRIBUTION, VERSION

        return {
            "ok": True,
            "package": DISTRIBUTION,
            "version": VERSION,
            "worker_api": list(WORKER_API_VERSIONS),
        }

    async def runtime_route(self, request: Any = None) -> dict[str, Any]:
        _, failure = self._parse("runtime_route", request)
        if failure is not None:
            return failure
        # 构造运行池服务要拿进程级的池锁，放工作线程；导入在事件循环上做完。
        import maafw_agent_env.core.runtime_pool  # noqa: F401

        from .runtime_route import resolve_runtime_pool_route

        try:
            route = await asyncio.to_thread(resolve_runtime_pool_route)
        except Exception as exc:  # noqa: BLE001 - 路由失败原文交给调用方
            return exception_result("runtime_route_unavailable", exc)
        return {"ok": True, "root": str(route.root), "pool_id": route.pool_id}

    async def runtime_check(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("runtime_check", request)
        if failure is not None:
            return failure
        # describe_unusable_runtime 在函数体里导入运行池：先在事件循环上导入好。
        import maafw_agent_env.core.agent_env.runtime_lease  # noqa: F401
        import maafw_agent_env.core.runtime_pool  # noqa: F401
        import maafw_agent_env.core.runtime_pool.binding  # noqa: F401

        from .runtime_check import describe_unusable_runtime

        problem = await asyncio.to_thread(
            describe_unusable_runtime, Path(parsed.project_path)
        )
        return {"ok": True, "problem": problem}

    async def storage_info(self, request: Any = None) -> dict[str, Any]:
        _, failure = self._parse("storage_info", request)
        if failure is not None:
            return failure
        from .pool_reconcile import agent_venvs_root, runtime_pool_root

        pool_root = runtime_pool_root()
        venvs_root = agent_venvs_root()
        return {
            "ok": True,
            "runtime_pool_root": str(pool_root),
            "has_runtimes": (pool_root / "runtimes").is_dir(),
            "agent_venvs_root": str(venvs_root),
            "has_agent_venvs": venvs_root.is_dir(),
        }

    async def env_lookup(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("env_lookup", request)
        if failure is not None:
            return failure
        from ..core.agent_env.project_env import project_environment_fingerprint
        from .env_cache import has_prepared_environment, load_prepared_environment

        project_path = Path(parsed.project_path)
        want = parsed.want_previously_prepared

        def lookup() -> dict[str, Any]:
            # 与端点原来的先后相同：指纹 → 「是不是更新」→ 缓存。
            fingerprint = project_environment_fingerprint(project_path)
            previously = (
                has_prepared_environment(project_path, fingerprint) if want else None
            )
            cached = load_prepared_environment(project_path, fingerprint)
            return {
                "ok": True,
                "fingerprint": fingerprint,
                "cached": cached,
                "previously_prepared": previously,
            }

        return await asyncio.to_thread(lookup)

    async def cache_prune(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("cache_prune", request)
        if failure is not None:
            return failure
        from .env_cache import prune_prepared_environments

        removed = await asyncio.to_thread(
            prune_prepared_environments, list(parsed.keep_project_paths)
        )
        return {"ok": True, "removed": int(removed)}

    async def borrow_return(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("borrow_return", request)
        if failure is not None:
            return failure
        from ..core.agent_env.runtime_lease import return_runtime_environment

        fields = {
            "runtime_pool_root": parsed.runtime_pool_root,
            "runtime_id": parsed.runtime_id,
            "lease_id": parsed.lease_id,
            "binding_version": parsed.binding_version,
        }
        self._leases.pop(
            (str(parsed.runtime_id or ""), str(parsed.lease_id or "")), None
        )
        try:
            released = await asyncio.to_thread(return_runtime_environment, **fields)
        except Exception as exc:  # noqa: BLE001 - 调用方照旧吞掉
            return exception_result("return_failed", exc)
        return {"ok": True, "released": _jsonable(released)}

    # ------------------------------------------------------------------
    # 句柄四件套：公共部分
    # ------------------------------------------------------------------

    async def _poll(self, family: str, request: Any) -> dict[str, Any]:
        _, failure = self._parse(f"{family}_poll", request)
        if failure is not None:
            return failure
        return await self._handles.poll(family, request)

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

    # ------------------------------------------------------------------
    # 借运行环境
    # ------------------------------------------------------------------

    async def borrow_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("borrow_start", request)
        if failure is not None:
            return failure
        from maafw_interface.interface.models import MaaFWAgent
        from pydantic import ValidationError

        agents = []
        for index, item in enumerate(parsed.agents):
            try:
                agents.append(MaaFWAgent.model_validate(item))
            except ValidationError as exc:
                return contract.invalid_request(
                    contract.error_entries(exc), prefix=("agents", index)
                )
        scope = _current_scope()
        started = self._handles.start(
            "borrow",
            lambda job: self._borrow_job(job, parsed, agents, scope),
            stop_grace=STOP_GRACE["borrow"],
            failure_code="borrow_failed",
            cancelled_result=_stopped(BORROW_CANCELLED_MESSAGE),
        )
        if started.get("ok"):
            self._borrow_ttl[started["handle"]] = parsed.lease_ttl_seconds
        return started

    async def _borrow_job(
        self, job: ServiceJob, request: Any, agents: list[Any], scope: Any
    ) -> dict[str, Any]:
        from ..core.agent_env.runtime_lease import (
            borrow_runtime_environment,
            return_runtime_lease,
        )
        from ..core.runtime_pool.host_environment import subprocess_proxy_scope
        from ..core.runtime_pool.installer import (
            MaaFWRuntimeInstallCancelled,
            install_process_factory_scope,
        )
        from ..core.worker_api import WORKER_API_VERSIONS

        job.on_stop(_ignore_stop_reason)
        send_log = self._emit_log(job)
        progress = self._emit_progress(job)

        def operation() -> Any:
            # 代理作用域按线程登记，在工作线程里进；安装子进程登记进调用方的进程作用域。
            with (
                subprocess_proxy_scope(request.proxy_url),
                install_process_factory_scope(
                    scope.popen if scope is not None else None
                ),
            ):
                return borrow_runtime_environment(
                    request.project_path,
                    runtime_pool_root=request.runtime_pool_root,
                    runtime_pool_id=request.runtime_pool_id,
                    lease_owner=request.lease_owner,
                    lease_ttl_seconds=request.lease_ttl_seconds,
                    send_log=send_log,
                    progress=progress,
                    cancel_event=job.stop_event,
                    agents=agents,
                    agent_env_root=request.agent_env_root,
                )

        try:
            lease = await self._run_worker(
                operation,
                scope,
                cancel=job.stop_event.set,
                release_cancelled=return_runtime_lease,
            )
        except MaaFWRuntimeInstallCancelled as exc:
            return _stopped(str(exc), exception_type=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - 原文交给调用方判环境类失败
            if job.stop_requested:
                return _stopped(str(exc), exception_type=type(exc).__name__)
            return exception_result("borrow_failed", exc)
        if job.stop_requested:
            # 停止之后恰好借成功：提供方自己还掉，结果记成停止。
            with contextlib.suppress(Exception):
                await asyncio.to_thread(return_runtime_lease, lease)
            return _stopped(BORROW_CANCELLED_MESSAGE)
        return {
            "ok": True,
            "python_executable": str(lease.python_executable),
            "venv_path": str(lease.venv_path),
            "packages": list(lease.packages),
            "maafw_version": lease.maafw_version,
            "maafw_requirement": lease.maafw_requirement,
            "runtime_id": lease.runtime_id,
            "runtime_pool_root": _text(lease.runtime_pool_root),
            "runtime_pool_id": lease.runtime_pool_id,
            "lease_id": lease.lease_id,
            "binding_dir": _text(lease.binding_dir),
            "binding_version": lease.binding_version,
            "native_dir": _text(lease.native_dir),
            "worker_env": {str(k): str(v) for k, v in lease.worker_env.items()},
            "agent_plans": [plan.model_dump(mode="json") for plan in lease.agent_plans],
            "worker_paths": _worker_paths(),
            "worker_api": list(WORKER_API_VERSIONS),
        }

    async def borrow_poll(self, request: Any = None) -> dict[str, Any]:
        reply = await self._poll("borrow", request)
        result = reply.get("result")
        if reply.get("done") and isinstance(result, Mapping) and result.get("ok"):
            # 结果交到调用方手里：租约归它，之后由它 borrow_return。
            job = self._handles.get("borrow", request)
            ttl = contract.DEFAULT_LEASE_TTL_SECONDS
            if job is not None:
                self._settled.add(job.handle)
                ttl = self._borrow_ttl.get(job.handle, ttl)
            self._record_handed_out(result, ttl)
        return reply

    async def borrow_stop(self, request: Any = None) -> dict[str, Any]:
        reply = self._stop("borrow", request)
        if not reply.get("ok"):
            return reply
        job = self._handles.get("borrow", request)
        if (
            job is not None
            and job.finished
            and not job.result_taken
            and isinstance(job.result, Mapping)
            and job.result.get("ok") is True
        ):
            # 已经借成、结果还没取走就被停：提供方还掉，结果改记停止。
            self._settle_borrow(job)
            job.result = _stopped(BORROW_CANCELLED_MESSAGE)
        return reply

    async def borrow_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("borrow", request)

    # ------------------------------------------------------------------
    # 准备环境
    # ------------------------------------------------------------------

    async def prepare_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("prepare_start", request)
        if failure is not None:
            return failure
        scope = _current_scope()
        return self._handles.start(
            "prepare",
            lambda job: self._prepare_job(job, parsed, scope),
            stop_grace=STOP_GRACE["prepare"],
            failure_code="prepare_failed",
            cancelled_result=_stopped(ENV_CANCELLED_MESSAGE),
        )

    async def _prepare_job(
        self, job: ServiceJob, request: Any, scope: Any
    ) -> dict[str, Any]:
        import maafw_interface.interface.agent_command  # noqa: F401
        from maafw_interface.interface import load_interface_model_cached
        from maafw_interface.interface.loader import MaaFWInterfaceLoadError

        # 导入检查（_warn_agent_imports）在工作线程里跑，它在函数体里导入的模块先在这里导入好。
        import maafw_agent_env.core.agent_env.import_check  # noqa: F401
        import maafw_agent_env.core.runtime_pool  # noqa: F401

        from ..core.agent_env.project_env import prepare_project_environment
        from ..core.runtime_pool.host_environment import subprocess_proxy_scope
        from ..core.runtime_pool.installer import install_process_factory_scope
        from .env_cache import store_prepared_environment
        from .runtime_route import resolve_runtime_pool_route

        job.on_stop(_ignore_stop_reason)
        send_log = self._emit_log(job)
        progress = self._emit_progress(job)
        project_path = Path(request.project_path)

        try:
            interface = await asyncio.to_thread(
                load_interface_model_cached, project_path
            )
        except MaaFWInterfaceLoadError as exc:
            return exception_result("interface_load_failed", exc)
        except Exception as exc:  # noqa: BLE001
            return exception_result("prepare_failed", exc)

        pool_root = request.runtime_pool_root
        pool_id = request.runtime_pool_id
        if pool_root is None:
            try:
                route = await asyncio.to_thread(resolve_runtime_pool_route)
            except Exception as exc:  # noqa: BLE001
                return exception_result("runtime_route_unavailable", exc)
            pool_root = str(route.root)
            if pool_id is None:
                pool_id = route.pool_id

        def operation() -> dict[str, Any]:
            with (
                subprocess_proxy_scope(request.proxy_url),
                install_process_factory_scope(
                    scope.popen if scope is not None else None
                ),
            ):
                return prepare_project_environment(
                    project_path,
                    interface,
                    runtime_pool_root=pool_root,
                    runtime_pool_id=pool_id,
                    send_log=send_log,
                    progress=progress,
                    cancel_event=job.stop_event,
                    lenient_health_check=request.lenient_health_check,
                )

        worker = asyncio.ensure_future(asyncio.to_thread(operation))
        if scope is not None:
            scope.retain_worker(worker)
        try:
            result = await asyncio.shield(worker)
        except Exception as exc:  # noqa: BLE001
            if job.stop_requested:
                return _stopped(str(exc), exception_type=type(exc).__name__)
            return exception_result("prepare_failed", exc)

        agents = result.get("agents")
        warnings = agents.get("healthWarnings") if isinstance(agents, Mapping) else None
        health_warnings = [str(item) for item in warnings or ()]
        stored = False
        if not job.detached:
            # 调用方已脱手（端点被取消）时不做导入检查、不写缓存：与原来端点被取消后
            # 那段代码不再执行一致。
            if request.import_check == "warn":
                await asyncio.to_thread(
                    _warn_agent_imports, project_path, result, send_log
                )
            if request.store_cache and not health_warnings and not job.detached:
                await asyncio.to_thread(
                    store_prepared_environment,
                    project_path,
                    str(result.get("projectFingerprint") or "")
                    or request.fallback_fingerprint,
                    result,
                )
                stored = True
        return {
            "ok": True,
            "environment": result,
            "health_warnings": health_warnings,
            "stored": stored,
        }

    async def prepare_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("prepare", request)

    async def prepare_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop("prepare", request)

    async def prepare_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("prepare", request)

    # ------------------------------------------------------------------
    # 更新预检
    # ------------------------------------------------------------------

    async def trial_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("trial_start", request)
        if failure is not None:
            return failure
        scope = _current_scope()
        return self._handles.start(
            "trial",
            lambda job: self._trial_job(job, parsed, scope),
            stop_grace=STOP_GRACE["trial"],
            failure_code="prepare_failed",
            cancelled_result=_stopped(ENV_CANCELLED_MESSAGE),
        )

    async def _trial_job(
        self, job: ServiceJob, request: Any, scope: Any
    ) -> dict[str, Any]:
        from maafw_interface.interface import load_interface_model_cached

        import maafw_agent_env.core.agent_env  # noqa: F401  check_staging_agent_imports 在函数体里导入它
        import maafw_agent_env.core.runtime_pool  # noqa: F401

        from ..core.agent_env.project_env import (
            prepare_project_environment,
            project_environment_fingerprint,
        )
        from ..core.runtime_pool.host_environment import subprocess_proxy_scope
        from ..core.runtime_pool.installer import install_process_factory_scope
        from .env_cache import load_prepared_environment
        from .env_trial import (
            MaaFWAgentImportMissingError,
            check_staging_agent_imports,
            precheck_agent_root,
            trial_environment,
        )
        from .pool_reconcile import runtime_pool_root
        from .runtime_route import resolve_runtime_pool_route

        job.on_stop(_ignore_stop_reason)
        send_log = self._emit_log(job)
        root = Path(request.project_path)
        agent_root = precheck_agent_root(
            request.runtime_pool_root or runtime_pool_root()
        )
        cancel_event = job.stop_event

        def prepare(agent_env_root: Path) -> None:
            # 与 ``project_environment.prepare_project_environment_sync`` 同一条流水线
            # （严格健康检查、不写缓存）：先看缓存，再读 interface、解析路由、进代理作用域准备。
            fingerprint = project_environment_fingerprint(root)
            if load_prepared_environment(root, fingerprint) is not None:
                return
            interface = load_interface_model_cached(root)
            route = resolve_runtime_pool_route()
            # 安装子进程登记进调用方的进程作用域只包准备这一段（原来 ``env_confirm`` 包的就是
            # prepare 本身，导入检查在它外面）。
            with (
                subprocess_proxy_scope(request.proxy_url),
                install_process_factory_scope(
                    scope.popen if scope is not None else None
                ),
            ):
                result = prepare_project_environment(
                    root,
                    interface,
                    runtime_pool_root=route.root,
                    runtime_pool_id=route.pool_id,
                    agent_env_root=agent_env_root,
                    send_log=send_log,
                    cancel_event=cancel_event,
                    lenient_health_check=False,
                )
            agents = result.get("agents")
            warnings = (
                agents.get("healthWarnings") if isinstance(agents, Mapping) else None
            )
            if warnings:
                send_log(LENIENT_PASS_LOG)

        def operation() -> None:
            # 不论成败，离开时删掉本次专用的预检子目录（在终态之前做完）。
            with trial_environment(root, agent_root) as trial:
                prepare(trial.agent_env_root)
                # 已停止就不再查导入：调用方随后按取消收尾。
                if not cancel_event.is_set():
                    check_staging_agent_imports(
                        root,
                        trial.agent_env_root,
                        send_log,
                        previous_version=request.previous_version,
                    )

        worker = asyncio.ensure_future(asyncio.to_thread(operation))
        if scope is not None:
            scope.retain_worker(worker)
        try:
            await asyncio.shield(worker)
        except MaaFWAgentImportMissingError as exc:
            return {
                "ok": False,
                "code": "agent_module_missing",
                "message": str(exc),
                "detail": {
                    "modules": [finding.module for finding in exc.findings],
                    "exception_type": type(exc).__name__,
                },
            }
        except Exception as exc:  # noqa: BLE001
            if job.stop_requested:
                return _stopped(str(exc), exception_type=type(exc).__name__)
            return exception_result("prepare_failed", exc)
        return {"ok": True}

    async def trial_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("trial", request)

    async def trial_stop(self, request: Any = None) -> dict[str, Any]:
        return self._stop("trial", request)

    async def trial_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("trial", request)

    # ------------------------------------------------------------------
    # 对账回收（没有取消点，不登记 _stop）
    # ------------------------------------------------------------------

    async def reconcile_start(self, request: Any = None) -> dict[str, Any]:
        parsed, failure = self._parse("reconcile_start", request)
        if failure is not None:
            return failure
        started = self._handles.start(
            "reconcile",
            lambda job: self._reconcile_job(job, parsed),
            stop_grace=STOP_GRACE["reconcile"],
        )
        if parsed.detach and started.get("ok"):
            # 调用方不收结果：句柄当场脱手，回收跑完提供方自己丢掉。
            self._handles.close("reconcile", {"handle": started["handle"]})
        return started

    async def _reconcile_job(self, job: ServiceJob, request: Any) -> dict[str, Any]:
        from .pool_reconcile import (
            reconcile_after_project_update,
            reconcile_agent_venvs,
            reconcile_runtime_pool,
        )

        # 回收没有取消点：退出时的「置停止」不取消这个作业，让它在 2 秒里有机会跑完。
        job.on_stop(_ignore_stop_reason)
        keep = list(request.keep_paths)

        def operation() -> Any:
            if request.target == "agent_venvs":
                reconcile_agent_venvs(keep)
                return None
            if request.updated_project_path is not None:
                return reconcile_after_project_update(
                    keep,
                    request.updated_project_path,
                    request.previous_version,
                    reason=request.reason or "project-update",
                )
            return reconcile_runtime_pool(keep, reason=request.reason or "")

        try:
            report = await asyncio.to_thread(operation)
        except Exception as exc:  # noqa: BLE001 - 回收函数本身把意外吞成日志，漏网的按 bug 记
            if request.detach:
                # 调用方不收结果：照原来后台线程那句记下来。
                _reconcile_logger.opt(exception=True).warning(
                    f"MFW 运行池后台回收失败（{request.reason or ''}）"
                )
            return exception_result("internal_error", exc)
        if request.target == "runtime_pool" and report is None:
            return {
                "ok": True,
                "outcome": "skipped",
                "reason": "abstained",
                "message": RECONCILE_ABSTAINED_MESSAGE,
            }
        return {"ok": True, "report": _jsonable(report)}

    async def reconcile_poll(self, request: Any = None) -> dict[str, Any]:
        return await self._poll("reconcile", request)

    async def reconcile_close(self, request: Any = None) -> dict[str, Any]:
        return self._close("reconcile", request)

    # ------------------------------------------------------------------
    # 停用、退出
    # ------------------------------------------------------------------

    def service_blockers(self) -> list[str]:
        """``teardown_blockers`` 的内容：只读内存表，不等。"""

        reasons: list[str] = []
        preparing = len(self._handles.active(("borrow", "prepare", "trial")))
        if preparing:
            reasons.append(BLOCKER_PREPARING.format(count=preparing))
        if self._handles.active(("reconcile",)):
            reasons.append(BLOCKER_RECONCILING)
        leases = self._outstanding_leases()
        if leases:
            reasons.append(BLOCKER_LEASES.format(count=leases))
        return reasons

    async def shutdown_services(self, *, teardown: bool) -> None:
        """停用（``teardown=False``）或退出（``teardown=True``）时收掉句柄表。

        - 停用：对在途作业置停止、取消作业任务；没被取走的租约还掉；清空句柄表。
        - 退出：对在途作业置停止，在途作业与提供方自己的还租约一起最多等 2 秒，然后清表；
          没被取走的租约还掉。停止之后才借成的，作业自己会还。
        """

        loop = asyncio.get_running_loop()
        deadline = loop.time() + TEARDOWN_WAIT_SECONDS
        reason = "teardown" if teardown else "disable"
        if teardown:
            self._handles.stop_all(reason)
            for job in self._handles.jobs():
                if job.finished:
                    self._settle_borrow(job)
            pending = [
                job.task for job in self._handles.active() if job.task is not None
            ]
            pending.extend(self._cleanups)
            if pending:
                await asyncio.wait(pending, timeout=max(0.0, deadline - loop.time()))
            await self._handles.shutdown(0, reason)
        else:
            self._handles.abort_all(reason)
        remaining = max(0.0, deadline - loop.time())
        if self._cleanups and remaining > 0:
            await asyncio.wait(set(self._cleanups), timeout=remaining)
        self._leases.clear()


def _warn_agent_imports(
    root_path: Path, result: Mapping[str, Any], log: Callable[[str], None]
) -> None:
    """按准备结果里的 agent 计划做导入静态检查，结论只进日志；检查失败静默放行。

    与端点原来的 ``_warn_agent_imports`` 同文同口径（工作线程里跑）。
    """

    try:
        from maafw_interface.interface.agent_command import MaaFWAgentCommandPlan

        from ..core.agent_env.import_check import (
            check_agent_plan_imports,
            log_agent_import_reports,
        )

        agents = result.get("agents") or {}
        plans = [
            MaaFWAgentCommandPlan.model_validate(item)
            for item in (agents.get("plans") or [])
        ]
        reports = check_agent_plan_imports(root_path, plans)
        log_agent_import_reports(reports, log, blocking=False)
    except Exception as exc:  # noqa: BLE001 - 提示性检查，出错不影响准备结果
        _env_logger.warning(f"agent 导入检查没能完成：{exc}")


__all__ = [
    "AgentEnvServices",
    "BLOCKER_LEASES",
    "BLOCKER_PREPARING",
    "BLOCKER_RECONCILING",
    "STOP_GRACE",
    "TEARDOWN_WAIT_SECONDS",
    "UNKNOWN_HANDLE_MESSAGE",
]
