"""服务契约兼容核对：用上一发行版的 ``contract.py`` 校验当前专项共用库拼出的每种请求。

MFW 服务化实施方案 §2.2、§8、§11 D3 定的兼容规则：请求新增字段必须可选、缺省等于旧行为；字段语义变了
走新的 ``v2`` 操作；提供方忽略多出来的键。共用库不依赖三块服务插件，「新共用库 + 旧提供方」是实际会
出现的组合（宿主装插件时会把别的已装插件钉在当前版本），所以发版前用本脚本核一遍。

用法（在积木仓根跑；解释器要有 pydantic，例如仓库根的 ``.venv-dev``）::

    python scripts/contract_compat.py --self                 # 只对当前工作树自检（0.3.0 首发时用）
    python scripts/contract_compat.py --base auto-mas-maafw-runner-v0.3.0 ...
    python scripts/contract_compat.py --base 0a1b2c3         # 三块都用同一个提交作基线
    python scripts/contract_compat.py --base runner=<引用> --base project_update=<引用> --base agent_env=<引用>
    python scripts/contract_compat.py --self --json out.json # 另存一份机器可读的结果

不给 ``--base`` 也不给 ``--self`` 时，每块取发行标签 ``<发行包名>-v<版本>`` 里版本最高的那个作基线；
没有标签就报错退出，请显式给 ``--base``。基线里的 ``contract.py`` 用 ``git show <引用>:<路径>`` 取出，
放进临时目录单独导入（它只依赖 pydantic），不碰工作区。共用库与解析库一律用**当前工作树**的源码
（脚本把 ``packages/*/src`` 插到 ``sys.path`` 前面），不用 venv 里装的版本。

核对什么：

1. 取样：调用共用库 ``maafw_adapter_kit.services`` 的每个请求构造函数（最少参数、全部参数各一份），再用
   一个只记录请求的假解析器把 ``Operation``（每个长操作族：正常跑完、开始前已停、带 ``limit``）、
   ``ProjectOpener``、交回预约里的几步真跑一遍，记下共用库实际发出的每个请求。
2. 每份请求：能 ``json.dumps`` 且往返不变；当前契约校验通过、没有当前契约不认识的键（拼写错误）；
   基线契约校验通过（旧提供方会受理）；比基线多出来的键必须是当前契约里的可选字段。
3. 契约对契约（有基线时）：基线有的操作当前不许删；当前比基线新加的字段必须可选；基线里可选的字段
   不许变成必填；字段注解变了记警告（真改了类型由第 2 条的取样校验抓）。
4. 覆盖：共用库的 ``ADAPTER_REQUIRES``、``PROJECT_PEEK_OPS``、``SHELL_IMPORT_OPS`` 里每个操作至少有一份
   取样；缺了说明共用库加了新调用而本脚本没跟上，要补取样。

属主服务 ``maafw.owner.<专项>.v1.*`` 的请求由项目更新拼、专项共用库提供，没有 ``contract.py``，不在这里核。

退出码：0 全部比过且通过；1 有不兼容或取样失败；2 用法 / 环境错误；3 没有不兼容，但有些提供方因为
基线里没有 ``contract.py``（例如 0.2.0）无从比较。
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import types
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: 三块服务插件：键 → (发行包名, contract.py 在仓库里的路径, 操作名不带前缀时补的服务名前缀)
PROVIDERS: dict[str, tuple[str, str, str]] = {
    "agent_env": (
        "auto-mas-maafw-agent-env",
        "packages/auto-mas-maafw-agent-env/src/maafw_agent_env/contract.py",
        "maafw.agent_env.v1",
    ),
    "runner": (
        "auto-mas-maafw-runner",
        "packages/auto-mas-maafw-runner/src/maafw_runner/contract.py",
        "maafw.runner.v1",
    ),
    "project_update": (
        "auto-mas-maafw-project-update",
        "packages/auto-mas-maafw-project-update/src/maafw_project_update/contract.py",
        "maafw.project.v1",
    ),
}
#: 服务名前缀 → 提供方键
PREFIX_OWNER = {
    "maafw.agent_env.v1": "agent_env",
    "maafw.runner.v1": "runner",
    "maafw.project.v1": "project_update",
    "maafw.project_update.v1": "project_update",
}

EXIT_OK = 0
EXIT_INCOMPATIBLE = 1
EXIT_USAGE = 2
EXIT_NOT_COMPARABLE = 3


class UsageError(Exception):
    pass


# ---------------------------------------------------------------------------
# 载入契约
# ---------------------------------------------------------------------------


@dataclass
class Contract:
    key: str
    source: str  # 「工作树」或 git 引用
    models: dict[str, Any] | None  # 服务名 → 请求模型；None = 这一版没有 contract.py
    note: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _import_contract(path: Path, module_name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise UsageError(f"导入不了 {path}")
    module = importlib.util.module_from_spec(spec)
    # pydantic 按 sys.modules[模型.__module__] 解析 ``from __future__ import annotations`` 的注解
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _service_models(module: types.ModuleType, prefix: str) -> dict[str, Any]:
    raw = getattr(module, "REQUEST_MODELS", None)
    if not isinstance(raw, Mapping):
        raise UsageError(f"{module.__name__} 没有 REQUEST_MODELS")
    return {
        (name if name.startswith("maafw.") else f"{prefix}.{name}"): model
        for name, model in raw.items()
    }


def load_contract(
    root: Path, key: str, ref: str | None, workdir: Path, tag: str
) -> Contract:
    """``ref`` 为 None 时读工作树里的文件，否则 ``git show <ref>:<路径>``。"""

    _dist, rel, prefix = PROVIDERS[key]
    target = workdir / f"{tag}_{key}_contract.py"
    if ref is None:
        source_path = root / rel
        if not source_path.is_file():
            return Contract(key, "工作树", None, f"工作树里没有 {rel}")
        target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        source = "工作树"
    else:
        shown = _git(root, "show", f"{ref}:{rel}")
        if shown.returncode != 0:
            exists = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            if exists.returncode != 0:
                raise UsageError(f"git 引用不存在：{ref}")
            return Contract(key, ref, None, f"{ref} 里没有 {rel}")
        target.write_text(shown.stdout, encoding="utf-8")
        source = ref
    module = _import_contract(target, f"_contract_compat_{tag}_{key}")
    return Contract(key, source, _service_models(module, prefix))


def latest_release_tag(root: Path, dist: str) -> str | None:
    listed = _git(root, "tag", "--list", f"{dist}-v*")
    if listed.returncode != 0:
        return None
    best: tuple[tuple[int, ...], str] | None = None
    pattern = re.compile(re.escape(dist) + r"-v(\d+(?:\.\d+)*)$")
    for line in listed.stdout.split():
        match = pattern.match(line.strip())
        if match is None:
            continue
        version = tuple(int(part) for part in match.group(1).split("."))
        if best is None or version > best[0]:
            best = (version, line.strip())
    return None if best is None else best[1]


# ---------------------------------------------------------------------------
# 模型工具
# ---------------------------------------------------------------------------


def _nested_model(annotation: Any) -> Any:
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        return annotation
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        for arg in typing.get_args(annotation):
            found = _nested_model(arg)
            if found is not None:
                return found
    return None


def _field_index(model: Any, prefix: str = "") -> dict[str, tuple[Any, bool]]:
    """``路径 → (注解, 是否必填)``，逐层展开嵌套的请求模型。"""

    index: dict[str, tuple[Any, bool]] = {}
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        index[path] = (info.annotation, info.is_required())
        nested = _nested_model(info.annotation)
        if nested is not None:
            index.update(_field_index(nested, f"{path}."))
    return index


def _unknown_paths(model: Any, data: Any, prefix: str = "") -> list[str]:
    """请求里模型不认识的键（按路径，逐层；与各 contract.py 的 ``unknown_keys`` 同一口径）。"""

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
            found.extend(_unknown_paths(nested, value, f"{path}."))
    return found


def _validation_errors(model: Any, data: Any) -> list[str]:
    try:
        model.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - pydantic.ValidationError，不带输入值地列出来
        errors = getattr(exc, "errors", None)
        if not callable(errors):
            return [type(exc).__name__]
        return [
            f"{'.'.join(str(p) for p in item['loc']) or '请求'}:{item['type']}"
            for item in errors(include_input=False, include_url=False)
        ]
    return []


def _annotation_text(annotation: Any) -> str:
    text = annotation.__name__ if isinstance(annotation, type) else repr(annotation)
    return re.sub(r"_contract_compat_\w+?\.", "", text.replace("typing.", ""))


# ---------------------------------------------------------------------------
# 取样：共用库实际拼出的请求
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    name: str
    label: str
    request: Any


class _Recorder:
    """只记录请求的假解析器：``_start`` 回句柄，``_poll`` 一次就 ``done``，其余回 ``{"ok": true}``。"""

    accepting = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.results: dict[str, dict[str, Any]] = {}

    def require(self, name: str) -> Callable[[Any], Any]:
        async def method(request: Any = None) -> dict[str, Any]:
            self.calls.append((name, copy.deepcopy(request)))
            op = name.rsplit(".", 1)[1]
            family = name.rsplit("_", 1)[0]
            if op.endswith("_start"):
                return {"ok": True, "handle": "0" * 32, "stop_grace": None}
            if op.endswith("_poll"):
                result = self.results.get(family, {"ok": True})
                return {
                    "ok": True,
                    "events": [],
                    "cursor": int((request or {}).get("cursor") or 0),
                    "done": True,
                    "result": dict(result),
                    "dropped": 0,
                }
            if op.endswith("_close"):
                return {"ok": True, "detached": False}
            return {"ok": True}

        return method


class _Section:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


class MaaFWConfig:
    """``record_payload`` 读的那几项；类名决定 ``kind``。"""

    def __init__(self, *, full: bool) -> None:
        when = datetime(2026, 11, 24, 8, 0, tzinfo=timezone.utc) if full else None
        self.Info = _Section(
            Name="取样托管" if full else None, Path=Path("C:/p") if full else None
        )
        self.Embedded = _Section(
            Report={"ok": True} if full else None,
            SourceVersion="v1.0.0" if full else None,
            ImportedAt=when,
            FollowSource=full,
        )
        self.Update = _Section(
            Channel="stable" if full else None,
            Source="GitHub" if full else None,
            AutoUpdateMode="BeforeRun" if full else None,
            PackageMode="Full" if full else None,
            ProxyAddress="http://u:p@127.0.0.1:1" if full else None,
            MirrorChyanCDK="cdk" if full else None,
        )
        self.is_locked = full


class _Dumpable:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(
        self, mode: str = "python", by_alias: bool = False
    ) -> dict[str, Any]:
        return copy.deepcopy(self._data)


class _Plan(_Dumpable):
    def __init__(self, agents: list[_Dumpable]) -> None:
        super().__init__({"tasks": [], "globalOptions": {}})
        self.declaredAgents = agents


def _install_fake_sdk_logger() -> None:
    """共用库的惰性 logger 第一次写日志时才 ``from auto_mas_core.host.utils import get_logger``。

    这里不要宿主：先放一个只有 ``get_logger``（标准 logging）的假 SDK 进 ``sys.modules``，免得真装了
    SDK 的解释器在取样时拉起宿主。只影响本进程。
    """

    import logging

    if "auto_mas_core" in sys.modules:
        return
    sdk = types.ModuleType("auto_mas_core")
    host = types.ModuleType("auto_mas_core.host")
    utils = types.ModuleType("auto_mas_core.host.utils")
    utils.get_logger = lambda name: logging.getLogger(f"contract_compat.{name}")  # type: ignore[attr-defined]
    sdk.host = host  # type: ignore[attr-defined]
    host.utils = utils  # type: ignore[attr-defined]
    sys.modules.update(
        {
            "auto_mas_core": sdk,
            "auto_mas_core.host": host,
            "auto_mas_core.host.utils": utils,
        }
    )


def build_samples(root: Path) -> tuple[list[Sample], list[str], set[str]]:
    """返回 ``(取样, 取样失败的说明, 要覆盖的操作名)``。"""

    for src in sorted((root / "packages").glob("*/src")):
        if str(src) not in sys.path:
            sys.path.insert(0, str(src))
    _install_fake_sdk_logger()
    from maafw_adapter_kit import owner_entry, services

    samples: list[Sample] = []
    problems: list[str] = []

    def add(name: str, label: str, request: Any) -> None:
        samples.append(Sample(name, label, copy.deepcopy(request)))

    def guarded(label: str, make: Callable[[], None]) -> None:
        try:
            make()
        except Exception as exc:  # noqa: BLE001 - 共用库改了签名时提示补取样
            problems.append(f"取样「{label}」失败：{type(exc).__name__}: {exc}")

    s = services
    R, P, U = s.RUNNER, s.PROJECT, s.PROJECT_UPDATE
    record_min = owner_entry.record_payload(
        "00000000-0000-0000-0000-000000000001", MaaFWConfig(full=False)
    )
    record_full = owner_entry.record_payload(
        "00000000-0000-0000-0000-000000000001", MaaFWConfig(full=True), order=3
    )
    controller = {"name": "Win32", "type": "Win32", "win32": {"class_regex": ".*"}}
    spec_min: dict[str, Any] = {}
    spec_full: dict[str, Any] = {}

    def specs() -> None:
        spec_min.update(
            s.desktop_spec(
                launch_mode="Direct",
                game_path=None,
                launcher_path=None,
                url="",
                arguments=None,
                wait_seconds=None,
                unity_resolution=None,
                close_mode="OnFailure",
                configured_hwnd=None,
            )
        )
        spec_full.update(
            s.desktop_spec(
                launch_mode="Launcher",
                game_path=Path("C:/g/game.exe"),
                launcher_path=Path("C:/g/launcher.exe"),
                url="https://example.invalid",
                arguments=["-a"],
                wait_seconds=30,
                unity_resolution=(1280, 720),
                close_mode="Always",
                configured_hwnd=123,
                game_path_error=ValueError("读不到游戏路径"),
                launcher_path_error="读不到启动器路径",
            )
        )

    guarded("desktop_spec", specs)
    starts: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def start(family: str, label: str, request: dict[str, Any]) -> None:
        starts.setdefault(family, []).append((label, request))

    # ---- 运行 ----
    guarded(
        "account_open_request",
        lambda: add(
            f"{R}.account_open",
            "全部",
            s.account_open_request("automas-script-maafw:x", "账号", 1.5),
        ),
    )
    guarded(
        "account_request",
        lambda: add(f"{R}.account_close", "全部", s.account_request("acc")),
    )
    guarded(
        "account_request",
        lambda: start(s.RUNNER_PRETASK_KILL, "全部", s.account_request("acc")),
    )
    guarded(
        "desktop_check_request",
        lambda: add(f"{R}.desktop_check", "最少", s.desktop_check_request(spec_min)),
    )
    guarded(
        "desktop_check_request",
        lambda: add(f"{R}.desktop_check", "全部", s.desktop_check_request(spec_full)),
    )
    guarded(
        "desktop_launch_request",
        lambda: start(
            s.RUNNER_DESKTOP_LAUNCH,
            "无控制器",
            s.desktop_launch_request("acc", spec_min, None),
        ),
    )
    guarded(
        "desktop_launch_request",
        lambda: start(
            s.RUNNER_DESKTOP_LAUNCH,
            "全部",
            s.desktop_launch_request("acc", spec_full, controller),
        ),
    )
    guarded(
        "desktop_quit_request",
        lambda: start(
            s.RUNNER_DESKTOP_QUIT,
            "最少",
            s.desktop_quit_request("acc", spec_min, mode="retry"),
        ),
    )
    guarded(
        "desktop_quit_request",
        lambda: start(
            s.RUNNER_DESKTOP_QUIT,
            "全部",
            s.desktop_quit_request(
                "acc",
                spec_full,
                mode="final",
                controller=controller,
                controller_type="Win32",
                failed=True,
            ),
        ),
    )
    for ask, path in (("never", None), ("if_unresolved", Path("C:/adb/adb.exe"))):
        guarded(
            "device_adb_path_request",
            lambda ask=ask, path=path: add(
                f"{R}.device_adb_path",
                ask,
                s.device_adb_path_request(
                    emulator_id="e",
                    device_uid="d",
                    configured_path=path,
                    device_title=None if path is None else "MuMu",
                    address="127.0.0.1:16384",
                    host_adb_path=None if path is None else "C:/adb/adb.exe",
                    ask_toolkit=ask,
                ),
            ),
        )
    for label, profile in (
        ("无档案", None),
        (
            "带档案",
            {
                "emulator_type": "mumu",
                "screencap_extra": True,
                "input_extra": False,
                "config": {"k": 1},
            },
        ),
    ):
        guarded(
            "device_adb_config_request",
            lambda label=label, profile=profile: add(
                f"{R}.device_adb_config",
                label,
                s.device_adb_config_request(
                    emulator_id="e",
                    target_id="t",
                    device_uid="d",
                    address="127.0.0.1:16384",
                    adb_path=None if profile is None else "C:/adb/adb.exe",
                    profile=profile,
                    process_id=None if profile is None else 42,
                    process_started_at=None if profile is None else 1.5,
                    configured_screencap_methods=None
                    if profile is None
                    else ["Encode"],
                    configured_input_methods=None if profile is None else ["MaaTouch"],
                ),
            ),
        )
    guarded(
        "device_win32_config_request",
        lambda: add(
            f"{R}.device_win32_config",
            "全部",
            s.device_win32_config_request(
                controller=controller,
                configured_hwnd=123,
                configured_screencap_method="FramePool",
                configured_mouse_method="Seize",
                configured_keyboard_method="Seize",
            ),
        ),
    )
    for label, ctrl in (("无控制器", None), ("全部", controller)):
        guarded(
            "pretask_rerun_check_request",
            lambda label=label, ctrl=ctrl: add(
                f"{R}.pretask_rerun_check",
                label,
                s.pretask_rerun_check_request(
                    has_pretasks=ctrl is not None,
                    client_reset=False,
                    controller_type=None if ctrl is None else "Win32",
                    interface_loaded=ctrl is not None,
                    controller_name=None if ctrl is None else "Win32",
                    controller=ctrl,
                    configured_hwnd=None,
                ),
            ),
        )
    guarded(
        "pretask_request",
        lambda: start(
            s.RUNNER_PRETASK,
            "全部",
            s.pretask_request(
                account="acc",
                project_path=Path("C:/p"),
                pretasks=[{"name": "pre", "exec": "a.exe"}],
                run_time_limit_minutes=None,
                plan_env={"A": "1"},
                extra_env={"B": "2"},
                secrets=["s"],
            ),
        ),
    )
    guarded(
        "plan_request",
        lambda: start(
            s.RUNNER_PLAN,
            "最少",
            s.plan_request(
                account="acc",
                project_path=Path("C:/p"),
                plan=_Plan([]),
                device_config={"type": "Adb"},
                # 运行池两项在契约里必填非空（没有它们借不到运行环境），最少的请求也得带
                runtime_pool_root=Path("C:/pool"),
                runtime_pool_id="pool",
                lease_owner="automas-maafw-runner",
                run_time_limit_minutes=0,
                attachment_root=Path("C:/att"),
            ),
        ),
    )
    guarded(
        "plan_request",
        lambda: start(
            s.RUNNER_PLAN,
            "全部",
            s.plan_request(
                account="acc",
                project_path=Path("C:/p"),
                plan=_Plan([_Dumpable({"name": "agent", "childExec": "python"})]),
                device_config={"type": "Win32"},
                runtime_pool_root=Path("C:/pool"),
                runtime_pool_id="pool",
                lease_owner="automas-maafw-runner",
                run_time_limit_minutes=30,
                attachment_root=Path("C:/att"),
                task_time_limit_seconds=60,
                task_time_limit_overrides={"任务": 10},
                task_deadlines={"任务": 123.0},
                loop_guard=True,
                run_secrets=["pw"],
                project_log_secrets=["pw"],
                redaction_notice="已打码",
                game_start_source="desktop",
                game_started_at=1.5,
                game_start_disk_quiet=True,
                game_wait_seconds=5,
                proxy_url="http://127.0.0.1:1",
                agent_plans=[{"name": "agent"}],
                extra_env={"A": "1"},
                avd_emulator_id="avd",
            ),
        ),
    )

    # ---- agent 环境 ----
    add(f"{s.AGENT_ENV}.runtime_route", "无参数", {})
    guarded(
        "runtime_check_request",
        lambda: add(
            f"{s.AGENT_ENV}.runtime_check",
            "全部",
            s.runtime_check_request(Path("C:/p")),
        ),
    )

    # ---- 项目 / 项目更新 ----
    guarded(
        "owner_register_request",
        lambda: add(
            f"{P}.owner_register",
            "全部",
            s.owner_register_request("maafw_adapter", "maafw.owner.maafw_adapter.v1"),
        ),
    )
    guarded(
        "owner_unregister_request",
        lambda: add(
            f"{P}.owner_unregister", "全部", s.owner_unregister_request("maafw_adapter")
        ),
    )
    for op in ("managed_find", "project_peek", "run_reserve"):
        guarded(
            "script_request",
            lambda op=op: add(
                f"{P}.{op}",
                "全部",
                s.script_request("00000000-0000-0000-0000-000000000001"),
            ),
        )
    guarded(
        "run_release_request",
        lambda: add(f"{P}.run_release", "最少", s.run_release_request("key")),
    )
    guarded(
        "run_release_request",
        lambda: add(
            f"{P}.run_release",
            "全部",
            s.run_release_request("key", after_job="f" * 32, on_job_error="keep"),
        ),
    )
    guarded(
        "project_context_request",
        lambda: add(
            f"{P}.project_context", "最少", s.project_context_request(record_min)
        ),
    )
    guarded(
        "project_context_request",
        lambda: add(
            f"{P}.project_context",
            "全部",
            s.project_context_request(record_full, with_view_import_check=True),
        ),
    )
    guarded(
        "open_request",
        lambda: start(
            s.PROJECT_OPEN,
            "最少",
            s.open_request(script_id="x", owner="maafw_adapter", record=record_min),
        ),
    )
    guarded(
        "open_request",
        lambda: start(
            s.PROJECT_OPEN,
            "全部（秒数）",
            s.open_request(
                script_id="x",
                owner="maafw_adapter",
                record=record_full,
                script_name="托管",
                round_started_at=1.7e9,
            ),
        ),
    )
    guarded(
        "open_request",
        lambda: start(
            s.PROJECT_OPEN,
            "全部（datetime）",
            s.open_request(
                script_id="x",
                owner="maafw_adapter",
                record=record_full,
                script_name="托管",
                round_started_at=datetime(2026, 11, 24, tzinfo=timezone.utc),
            ),
        ),
    )
    guarded(
        "handle_request",
        lambda: add(f"{P}.open_release", "全部", s.handle_request("f" * 32)),
    )
    for phase in ("BeforeRun", "AfterRun"):
        guarded(
            "confirm_request",
            lambda phase=phase: start(
                s.PROJECT_CONFIRM,
                phase,
                s.confirm_request(
                    script_id="x", owner="o", record=record_full, phase=phase
                ),
            ),
        )
    guarded(
        "finish_request",
        lambda: start(
            s.PROJECT_FINISH,
            "全部",
            s.finish_request(
                script_id="x",
                owner="o",
                script_name="托管",
                record=record_full,
                sync_group=True,
                round_started_at=1.7e9,
            ),
        ),
    )
    guarded(
        "repair_request",
        lambda: start(
            s.PROJECT_REPAIR,
            "全部",
            s.repair_request(
                script_id="x",
                script_name="托管",
                record=record_full,
                kind="resource",
                already_checked=False,
            ),
        ),
    )
    guarded(
        "view_ensure_request",
        lambda: start(s.PROJECT_VIEW_ENSURE, "最少", s.view_ensure_request(None, "")),
    )
    guarded(
        "view_ensure_request",
        lambda: start(
            s.PROJECT_VIEW_ENSURE, "全部", s.view_ensure_request("x", Path("C:/p"))
        ),
    )
    guarded(
        "script_cloned_request",
        lambda: start(
            s.PROJECT_SCRIPT_CLONED,
            "全部",
            s.script_cloned_request(
                source_id="a", target_id="b", owner="o", source_record=record_full
            ),
        ),
    )
    guarded(
        "script_removed_request",
        lambda: start(
            s.PROJECT_SCRIPT_REMOVED,
            "全部",
            s.script_removed_request(script_id="x", owner="o"),
        ),
    )
    guarded(
        "update_request",
        lambda: start(
            s.PROJECT_UPDATE_UPDATE,
            "最少",
            s.update_request(
                script_id="x",
                owner="o",
                script_name="托管",
                record=record_min,
                phase="BeforeRun",
            ),
        ),
    )
    guarded(
        "update_request",
        lambda: start(
            s.PROJECT_UPDATE_UPDATE,
            "全部",
            s.update_request(
                script_id="x",
                owner="o",
                script_name="托管",
                record=record_full,
                phase="AfterRun",
                prefetch_paths={"payload": Path("C:/dl/p.zip")},
                prefetch_token="t",
                round_started_at=1.7e9,
            ),
        ),
    )
    for family in (s.PROJECT_UPDATE_PREFETCH, s.PROJECT_UPDATE_DISCOVER):
        guarded(
            "project_job_request",
            lambda family=family: start(
                family,
                "全部",
                s.project_job_request(script_id="x", owner="o", record=record_full),
            ),
        )
    guarded(
        "prefetch_discard_request",
        lambda: add(f"{U}.prefetch_discard", "全部", s.prefetch_discard_request("t")),
    )

    # 构造函数直接产出的 _start 请求也算一份取样
    for family, items in starts.items():
        for label, request in items:
            add(f"{family}_start", label, request)

    # ---- 用假解析器把共用库里真正发请求的路径跑一遍 ----
    recorder = _Recorder()
    client = s.ServiceClient(recorder, caller="contract_compat")
    recorder.results[s.RUNNER_PRETASK_EXIT_WATCH] = {"ok": True, "confirmed": True}
    recorder.results[s.PROJECT_OPEN] = {
        "ok": True,
        "outcome": "opened",
        "lease": None,
        "record_update": None,
        "env_confirm_needed": False,
    }

    async def drive() -> None:
        for family, items in starts.items():
            label, request = items[-1]
            await client.run(family, request)
            stopped = client.operation(family)
            stopped.stop()
            await stopped.run(request)
            await client.run(family, request, limit=100)
        opener = s.ProjectOpener(client)
        await opener.reserve(starts[s.PROJECT_OPEN][-1][1])
        await opener.prepare()
        opener._stop_in_background(s.STOP_REASON_CANCELLED)
        for _ in range(100):  # 后台任务发出 open_stop 为止（最多约 1 秒）
            if any(name == f"{s.PROJECT_OPEN}_stop" for name, _req in recorder.calls):
                break
            await asyncio.sleep(0.01)
        await opener.release()
        for account in ("acc", None):
            handle = await s._start_exit_watch(client, account)
            if handle is not None:
                await s._exit_confirmed(client, handle)
        await s._run_release(client, "key", after_job=None, on_job_error="release")
        await s._run_release(client, "key", after_job="f" * 32, on_job_error="keep")

    try:
        asyncio.run(drive())
    except Exception as exc:  # noqa: BLE001 - 共用库改了内部写法时提示补取样
        problems.append(f"用假解析器跑共用库失败：{type(exc).__name__}: {exc}")
    for name, request in recorder.calls:
        add(name, "实际发出", request)

    wanted = set(s.ADAPTER_REQUIRES) | set(s.PROJECT_PEEK_OPS) | set(s.SHELL_IMPORT_OPS)
    return samples, problems, wanted


# ---------------------------------------------------------------------------
# 核对
# ---------------------------------------------------------------------------


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    not_comparable: list[str] = field(default_factory=list)
    passed: dict[str, int] = field(default_factory=dict)
    compared: dict[str, int] = field(default_factory=dict)


def _owner_of(name: str) -> str | None:
    return PREFIX_OWNER.get(name.rsplit(".", 1)[0])


def check_samples(
    samples: list[Sample],
    current: dict[str, Contract],
    base: dict[str, Contract],
    report: Report,
) -> None:
    for sample in samples:
        where = f"{sample.name}（{sample.label}）"
        key = _owner_of(sample.name)
        if key is None:
            report.failures.append(f"{where}：不是三块服务插件的服务名")
            continue
        try:
            text = json.dumps(sample.request, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            report.failures.append(f"{where}：请求不是 JSON 值（{exc}）")
            continue
        if json.loads(text) != sample.request:
            report.failures.append(f"{where}：请求过一遍 JSON 后变了")
        now_models = current[key].models or {}
        now_model = now_models.get(sample.name)
        if now_model is None:
            report.failures.append(f"{where}：当前契约没有这个操作")
            continue
        ok = True
        for err in _validation_errors(now_model, sample.request):
            ok = False
            report.failures.append(f"{where}：当前契约不收（{err}）")
        for path in _unknown_paths(now_model, sample.request):
            ok = False
            report.failures.append(f"{where}：键 {path} 当前契约不认（拼写错误？）")
        base_contract = base[key]
        if base_contract.models is None:
            if ok:
                report.passed[key] = report.passed.get(key, 0) + 1
            continue
        base_model = base_contract.models.get(sample.name)
        report.compared[key] = report.compared.get(key, 0) + 1
        if base_model is None:
            ok = False
            report.failures.append(
                f"{where}：基线 {base_contract.source} 的提供方没有这个操作（新共用库调旧提供方会拿不到服务）"
            )
        else:
            for err in _validation_errors(base_model, sample.request):
                ok = False
                report.failures.append(
                    f"{where}：基线 {base_contract.source} 的契约不收（{err}）"
                )
            now_fields = _field_index(now_model)
            for path in _unknown_paths(base_model, sample.request):
                entry = now_fields.get(path)
                if entry is None:
                    continue  # 上面「当前契约不认」已经报过
                if entry[1]:
                    ok = False
                    report.failures.append(
                        f"{where}：键 {path} 基线没有、当前却是必填（新增字段必须可选，缺省等于旧行为）"
                    )
        if ok:
            report.passed[key] = report.passed.get(key, 0) + 1


def check_contracts(
    current: dict[str, Contract], base: dict[str, Contract], report: Report
) -> None:
    for key, base_contract in base.items():
        if base_contract.models is None:
            report.not_comparable.append(f"{key}：{base_contract.note}，无从比较")
            continue
        now = current[key].models or {}
        for name, base_model in base_contract.models.items():
            now_model = now.get(name)
            if now_model is None:
                report.failures.append(
                    f"{name}：基线 {base_contract.source} 有、当前删了（删操作是破坏性改动，应走 v2）"
                )
                continue
            before = _field_index(base_model)
            after = _field_index(now_model)
            for path, (annotation, required) in after.items():
                old = before.get(path)
                if old is None:
                    if required:
                        report.failures.append(
                            f"{name}：新增字段 {path} 是必填（旧共用库不会带它）"
                        )
                    continue
                if required and not old[1]:
                    report.failures.append(f"{name}：字段 {path} 原来可选、现在必填")
                if _annotation_text(old[0]) != _annotation_text(annotation):
                    report.warnings.append(
                        f"{name}：字段 {path} 的注解 {_annotation_text(old[0])} → {_annotation_text(annotation)}"
                    )
            for path, (_annotation, required) in before.items():
                if path not in after:
                    report.warnings.append(
                        f"{name}：字段 {path} 当前契约里没有了（旧共用库带来的会被忽略）"
                    )


def check_coverage(samples: list[Sample], wanted: set[str], report: Report) -> None:
    have = {sample.name for sample in samples}
    for name in sorted(wanted - have):
        report.failures.append(
            f"{name}：共用库的 requires 里有它，但本脚本没有取样，请补"
        )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _parse_bases(values: list[str]) -> dict[str, str]:
    bases: dict[str, str] = {}
    shared: str | None = None
    for value in values:
        key, sep, ref = value.partition("=")
        if not sep:
            shared = value
        elif key in PROVIDERS and ref:
            bases[key] = ref
        else:
            raise UsageError(
                f"--base 写法不对：{value!r}；提供方可选 {', '.join(PROVIDERS)}"
            )
    if shared is not None:
        for name in PROVIDERS:
            bases.setdefault(name, shared)
    return bases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--self",
        dest="self_check",
        action="store_true",
        help="基线就用当前工作树的契约（自检）",
    )
    group.add_argument(
        "--base",
        action="append",
        default=[],
        help="基线 git 引用；可写 <提供方>=<引用>，可给多次",
    )
    parser.add_argument(
        "--repo", type=Path, default=ROOT, help="积木仓根（缺省是本脚本所在仓库）"
    )
    parser.add_argument("--json", type=Path, help="另存一份机器可读的结果")
    args = parser.parse_args(argv)
    root: Path = args.repo.resolve()

    try:
        if args.self_check:
            refs: dict[str, str | None] = {key: None for key in PROVIDERS}
        else:
            given = _parse_bases(args.base)
            refs = {}
            for key, (dist, _rel, _prefix) in PROVIDERS.items():
                ref = given.get(key) or latest_release_tag(root, dist)
                if ref is None:
                    raise UsageError(
                        f"{dist} 没有发行标签（{dist}-v*），请用 --base 指定基线或用 --self 自检"
                    )
                refs[key] = ref
        with tempfile.TemporaryDirectory(prefix="contract-compat-") as tmp:
            workdir = Path(tmp)
            current = {
                key: load_contract(root, key, None, workdir, "now") for key in PROVIDERS
            }
            for key, contract in current.items():
                if contract.models is None:
                    raise UsageError(contract.note)
            base = {
                key: load_contract(root, key, refs[key], workdir, "base")
                for key in PROVIDERS
            }
            samples, problems, wanted = build_samples(root)
    except UsageError as exc:
        print(f"用法 / 环境错误：{exc}", file=sys.stderr)
        return EXIT_USAGE

    report = Report()
    report.failures.extend(problems)
    check_samples(samples, current, base, report)
    check_contracts(current, base, report)
    check_coverage(samples, wanted, report)

    print("服务契约兼容核对")
    print(f"  积木仓：{root}")
    for key in PROVIDERS:
        print(f"  {key}：基线 {base[key].source}；当前 工作树")
    print(
        f"  取样 {len(samples)} 份，覆盖 {len({s.name for s in samples})} 个服务名（要求覆盖 {len(wanted)} 个）"
    )
    for key in PROVIDERS:
        compared = report.compared.get(key, 0)
        passed = report.passed.get(key, 0)
        print(f"  {key}：通过 {passed} 份，其中与基线比过 {compared} 份")
    for title, items in (
        ("无从比较", report.not_comparable),
        ("警告", report.warnings),
        ("不兼容", report.failures),
    ):
        if items:
            print(f"{title}（{len(items)}）：")
            for item in items:
                print(f"  - {item}")
    if args.json is not None:
        payload = {
            "repo": str(root),
            "bases": {key: base[key].source for key in PROVIDERS},
            "samples": [
                {
                    "name": s.name,
                    "label": s.label,
                    "keys": sorted(s.request)
                    if isinstance(s.request, Mapping)
                    else None,
                }
                for s in samples
            ],
            "covered": sorted({s.name for s in samples}),
            "wanted": sorted(wanted),
            "passed": report.passed,
            "compared": report.compared,
            "not_comparable": report.not_comparable,
            "warnings": report.warnings,
            "failures": report.failures,
        }
        args.json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    if report.failures:
        print("结论：有不兼容")
        return EXIT_INCOMPATIBLE
    if report.not_comparable:
        print("结论：取样全部通过当前契约，但有提供方的基线没有 contract.py，无从比较")
        return EXIT_NOT_COMPARABLE
    print("结论：通过")
    return EXIT_OK


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
