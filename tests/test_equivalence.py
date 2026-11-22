"""宿主快照里的原函数与两个库的同名函数，对六个真实项目逐字节对拍。

两边都用宿主环境的解释器（``.venv-eqhost``，由 ``_src`` 的 ``uv.lock`` 建出）各起一个子进程：

- 宿主一侧：工作目录 ``_src``，从 ``app.task.MaaFW...`` 导入原函数；
- 库一侧：工作目录是临时目录，``PYTHONPATH`` 只放两个库的 ``src``，进程里 ``import app`` 必须失败。

两边的第三方包（pydantic、json5、packaging、maafw）是同一份，所以输出里没有任何字段需要归一化：
项目路径两边相同；``PI_CLIENT_MAAFW_VERSION`` 与预览里的 ``emulatorExtras`` 都取决于环境里装没装
maafw，两边同一个环境、结果相同。唯一按接口变化对齐的是客户端版本：宿主原函数自己读
``_src/res/version.json``，库改成由调用方传 ``client_version``，库一侧照宿主的读法读同一个文件传进去。

覆盖：interface 模型；预览（同名函数 ``build_interface_preview_data`` 及 ``apply_preview_plan_rules``）；
每个「控制器 × 资源」组合（含非默认组合）下每个预设与「全部任务」的计划；默认快照与快照归一化；
展开任务快照（勾选、红灯、今天不在运行日、interface 内已无、失效选项值、规则表不可选）及按它建的计划
（规则表的失败即结束、失败不计、字符串输入不回落 default 一并带上）；
pretask 计划（与一个普通任务同建，成功路径）；MaaEnd 用的标签与 MXU 换算；Win32 窗口规则匹配；
原生库版本、requirement、PE 架构。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "_src"
HOST_PYTHON = Path(
    os.environ.get(
        "MAAFW_EQ_HOST_PYTHON", ROOT / ".venv-eqhost" / "Scripts" / "python.exe"
    )
)
LIBRARY_PATHS = [
    ROOT / "packages" / "auto-mas-maafw-interface" / "src",
    ROOT / "packages" / "auto-mas-maafw-native" / "src",
]
WALKREF = Path("D:/MAS/test/walkref")
PROJECTS = ["m9a", "maaend", "mra", "starres", "maabbb", "maayys"]

_HOST_PREAMBLE = r"""
from app.task.MaaFW.tools.core.controller_win32.service import (
    MaaFWWin32ControllerService,
    MaaFWWin32Window,
    controller_has_window_rules,
)
from app.task.MaaFW.tools.core.interface.loader import load_interface_model
from app.task.MaaFW.tools.core.interface.models import (
    build_pretask_task_name,
    iter_pretasks,
)
from app.task.MaaFW.tools.core.interface.plan_rules import MaaFWPlanRules
from app.task.MaaFW.tools.core.interface.preview import (
    apply_preview_plan_rules,
    build_interface_preview_data,
)
from app.task.MaaFW.tools.core.native.pe import detect_pe_architecture
from app.task.MaaFW.tools.core.native.project_runtime import (
    PROJECT_MAAFW_DLL_NAME,
    probe_bundled_maafw_version,
    project_maafw_runtime_path,
    read_runtime_maafw_version,
)
from app.task.MaaFW.tools.core.native.requirement import (
    resolve_project_maafw_requirement,
)
from app.task.MaaFW.tools.core.runner.run_plan import (
    build_maafw_run_plan as build_plan,
    resolve_default_snapshot,
    select_snapshot_tasks,
)
from app.task.MaaFW.tools.core.runner.task_selection import (
    build_arranged_plan as build_arranged,
    expand_task_snapshot,
    inspect_task_snapshot,
)
from app.task.MaaFW.tools.embedded.shell_instances import (
    _Labels as Labels,
    _mxu_option_values as mxu_option_values,
)


def match_windows(controller, windows):
    return MaaFWWin32ControllerService().match_controller_windows(controller, windows)
"""

_LIBRARY_PREAMBLE = r"""
import functools
import importlib.util

assert importlib.util.find_spec("app") is None, "库一侧不应能导入宿主 app"

from maafw_interface.controller_win32.service import (
    MaaFWWin32ControllerService,
    MaaFWWin32Window,
    controller_has_window_rules,
)
from maafw_interface.embedded_labels import Labels, mxu_option_values
from maafw_interface.interface.loader import load_interface_model
from maafw_interface.interface.models import build_pretask_task_name, iter_pretasks
from maafw_interface.interface.plan_rules import MaaFWPlanRules
from maafw_interface.interface.preview import (
    apply_preview_plan_rules,
    build_interface_preview_data,
)
from maafw_interface.runner.run_plan import (
    build_maafw_run_plan,
    resolve_default_snapshot,
    select_snapshot_tasks,
)
from maafw_interface.runner.task_selection import (
    build_arranged_plan,
    expand_task_snapshot,
    inspect_task_snapshot,
)
from maafw_native.pe import detect_pe_architecture
from maafw_native.project_runtime import (
    PROJECT_MAAFW_DLL_NAME,
    probe_bundled_maafw_version,
    project_maafw_runtime_path,
    read_runtime_maafw_version,
)
from maafw_native.requirement import resolve_project_maafw_requirement

# 宿主原函数自己读 res/version.json（_load_client_version），库改由调用方传入：照同一读法读同一个文件。
_version = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")).get("version")
CLIENT_VERSION = _version if isinstance(_version, str) else ""
build_plan = functools.partial(build_maafw_run_plan, client_version=CLIENT_VERSION)
build_arranged = functools.partial(build_arranged_plan, client_version=CLIENT_VERSION)


def match_windows(controller, windows):
    return MaaFWWin32ControllerService().match_controller_windows(
        controller, lambda: windows
    )
"""

_BODY = r"""
import dataclasses
from collections.abc import Mapping

# 展开快照用的「今天」：固定成周三，结果不随跑测试的日子变
ISO_WEEKDAY = 3
WINDOWS = [
    (1, "UnityWndClass", "Endfield"),
    (2, "UnityWndClass", "星塔旅人"),
    (3, "Chrome_WidgetWin_1", "Game"),
    (1, "UnityWndClass", "Endfield"),
    (4, "UnityWndClass", "Honkai Impact 3rd"),
    (5, "UnityWndClass", "崩坏3"),
]


def dump(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: dump(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((dump(item) for item in value), key=repr)
    return value


def capture(fn):
    try:
        return {"ok": True, "value": dump(fn())}
    except Exception as exc:
        return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}


def compatible_tasks(interface, controller, resource):
    return [
        task
        for task in interface.task
        if (not task.controller or controller in task.controller)
        and (not task.resource or resource in task.resource)
    ]


def make_snapshot(interface, controller, resource):
    tasks = compatible_tasks(interface, controller, resource)[:5]
    if not tasks:
        return None, MaaFWPlanRules()
    names = [task.name for task in tasks]
    order = [*names, "interface 里没有的任务"]
    checked = dict.fromkeys(order, True)
    if len(names) > 1:
        checked[names[1]] = False  # 红灯
    schedules = {}
    if len(names) > 2:
        schedules[names[2]] = {
            "weekdays": [day for day in range(1, 8) if day != ISO_WEEKDAY]
        }
    options = {}
    for task in tasks:
        for option_name in task.option or []:
            definition = interface.option.get(option_name)
            if definition is not None and definition.type == "select" and definition.cases:
                options[task.name] = {option_name: "失效的取值"}
                break
        if options:
            break
    snapshot = {
        "taskOrder": order,
        "taskChecked": checked,
        "taskOptions": options,
        "taskSchedules": schedules,
        "keepUnchecked": True,
    }
    # 字符串输入没填时不回落 default：取这几个任务里第一个 input 选项的全部字段
    no_fallback = set()
    for task in tasks:
        for option_name in task.option or []:
            definition = interface.option.get(option_name)
            if definition is not None and definition.type == "input":
                no_fallback.update(
                    (option_name, item.name) for item in definition.inputs or []
                )
        if no_fallback:
            break
    rules = MaaFWPlanRules(
        unselectable={tasks[3].entry: "规则表里不可选"} if len(tasks) > 3 else {},
        abort_round={tasks[0].entry: "失败即结束本轮"},
        nonfatal={tasks[-1].entry: "失败不计"},
        no_default_fallback_inputs=frozenset(no_fallback),
    )
    return snapshot, rules


def expansion_result(project, interface, controller, resource):
    snapshot, rules = make_snapshot(interface, controller, resource)
    if snapshot is None:
        return None
    out = {"snapshot": snapshot}
    inspection = inspect_task_snapshot(
        project, interface, snapshot, iso_weekday=ISO_WEEKDAY
    )
    out["inspection"] = dump(inspection)
    out["offDayReasons"] = dump(inspection.off_day_reasons())
    holder = {}

    def expand():
        holder["expansion"] = expand_task_snapshot(
            project,
            interface,
            task_snapshot=snapshot,
            selected_preset=None,
            iso_weekday=ISO_WEEKDAY,
            rules=rules,
            inspection=inspection,
        )
        return holder["expansion"]

    out["expansion"] = capture(expand)
    expansion = holder.get("expansion")
    if expansion is not None:
        out["excludedTaskIds"] = dump(expansion.excluded_task_ids)
        out["arrangedPlan"] = capture(
            lambda: build_arranged(
                project,
                interface,
                expansion=expansion,
                inspection=inspection,
                task_ids=list(expansion.task_ids),
                task_options=dict(expansion.task_options),
                task_snapshot=snapshot,
                controller_name=controller,
                resource_name=resource,
                script_hotkeys=None,
                rules=rules,
            )
        )
    out["snapshotPlan"] = capture(
        lambda: build_plan(
            project,
            interface,
            controller_name=controller,
            resource_name=resource,
            task_snapshot=snapshot,
            excluded_task_reasons=inspection.off_day_reasons(),
        )
    )
    preview = build_interface_preview_data(project, interface).model_dump(
        mode="json", by_alias=True
    )
    apply_preview_plan_rules(preview, rules)
    out["previewWithRules"] = preview
    return out


def mxu_input(definition):
    cases = [case.name for case in definition.cases or []]
    kind = definition.type
    if kind in ("select", "scan_select"):
        return {"type": kind, "caseName": cases[-1] if cases else "扫描值"}
    if kind == "switch":
        return {"type": kind, "value": True}
    if kind == "checkbox":
        return {"type": kind, "caseNames": [*cases[:1], "不存在的取值"]}
    if kind in ("input", "hotkey"):
        fields = definition.inputs if kind == "input" else definition.hotkeys
        values = {item.name: "1" for item in fields or []}
        values["不存在的字段"] = "x"
        return {"type": kind, "values": values}
    return {"type": kind}


def labels_result(interface):
    labels = Labels(interface, None)
    raw = {name: mxu_input(definition) for name, definition in interface.option.items()}
    raw["不存在的选项"] = {"type": "select", "caseName": "a"}
    skipped = []
    values = mxu_option_values(raw, interface.option, "任务", labels, skipped)
    return {
        "tasks": {task.name: labels.task(task.name) for task in interface.task},
        "options": {name: labels.option(name) for name in interface.option},
        "values": dump(values),
        "skipped": skipped,
    }


def windows_result(interface):
    windows = [MaaFWWin32Window(*item) for item in WINDOWS]
    return {
        controller.name: {
            "hasRules": controller_has_window_rules(controller),
            "matches": capture(lambda: match_windows(controller, windows)),
        }
        for controller in interface.controller
    }


interface = load_interface_model(project)
combos = [
    (controller.name, resource.name)
    for controller in interface.controller
    for resource in interface.resource
    if not resource.controller or controller.name in resource.controller
]
presets = [preset.name for preset in interface.preset]
result = {
    "interface": dump(interface),
    "preview": dump(build_interface_preview_data(project, interface)),
    "combos": combos,
    "defaultSnapshots": {
        str(name): capture(
            lambda: resolve_default_snapshot(interface, selected_preset=name)
        )
        for name in [None, *presets]
    },
    "selectedTasks": {
        str(name): capture(
            lambda: select_snapshot_tasks(
                interface, selected_preset=name, task_snapshot=None
            )
        )
        for name in [None, *presets]
    },
    "plans": {},
    "expansions": {},
    "pretasks": {},
    "labels": labels_result(interface),
    "windows": windows_result(interface),
}
for controller, resource in combos:
    key = f"{controller} | {resource}"
    entry = {
        "preset:" + str(name): capture(
            lambda: build_plan(
                project,
                interface,
                controller_name=controller,
                resource_name=resource,
                selected_preset=name,
            )
        )
        for name in [None, *presets]
    }
    entry["allTasks"] = capture(
        lambda: build_plan(
            project,
            interface,
            controller_name=controller,
            resource_name=resource,
            task_ids=[task.name for task in interface.task],
        )
    )
    result["plans"][key] = entry
    result["expansions"][key] = expansion_result(project, interface, controller, resource)
    common = compatible_tasks(interface, controller, resource)
    for pretask in iter_pretasks(interface):
        name = build_pretask_task_name(pretask)
        result["pretasks"][f"{key} | {name}"] = capture(
            lambda: build_plan(
                project,
                interface,
                controller_name=controller,
                resource_name=resource,
                task_ids=[name, *[task.name for task in common[:1]]],
            )
        )

runtime = project_maafw_runtime_path(project)
result["native"] = {
    "runtime": str(runtime) if runtime else None,
    "version": read_runtime_maafw_version(runtime) if runtime else None,
    "bundled": probe_bundled_maafw_version(project),
    "requirement": resolve_project_maafw_requirement(project),
    "architecture": detect_pe_architecture(runtime / PROJECT_MAAFW_DLL_NAME)
    if runtime
    else None,
}
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
"""

_PROLOGUE = r"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
project = Path(sys.argv[1]).resolve()
"""


def _run(script: str, project: Path, *, cwd: Path, env: dict[str, str]) -> dict:
    assert HOST_PYTHON.is_file(), (
        f"缺宿主环境解释器 {HOST_PYTHON}：按仓库 README「等价对拍」一节建 .venv-eqhost，"
        "或用 MAAFW_EQ_HOST_PYTHON 指定"
    )
    version_file = SOURCE_ROOT / "res" / "version.json"
    assert version_file.is_file(), (
        f"缺 {version_file}（取自 048993fca 的 res/version.json）"
    )
    completed = subprocess.run(
        [str(HOST_PYTHON), "-c", script, str(project), str(version_file)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def _base_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    env["PYTHONUTF8"] = "1"
    return env


def host_result(project: Path) -> dict:
    return _run(
        _PROLOGUE + _HOST_PREAMBLE + _BODY, project, cwd=SOURCE_ROOT, env=_base_env()
    )


def library_result(project: Path, workdir: Path) -> dict:
    env = _base_env()
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in LIBRARY_PATHS)
    return _run(_PROLOGUE + _LIBRARY_PREAMBLE + _BODY, project, cwd=workdir, env=env)


def _first_difference(left, right, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: {left!r} != {right!r}"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}.{key}: 只在一边出现"
            found = _first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: 长度 {len(left)} != {len(right)}"
        for index, (a, b) in enumerate(zip(left, right)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else f"{path}: {left!r} != {right!r}"


@pytest.mark.parametrize("name", PROJECTS)
def test_host_snapshot_and_libraries_are_equivalent(name: str, tmp_path: Path) -> None:
    project = WALKREF / name
    host = host_result(project)
    library = library_result(project, tmp_path)
    host_text = json.dumps(host, ensure_ascii=False, sort_keys=True)
    library_text = json.dumps(library, ensure_ascii=False, sort_keys=True)
    # 客户端版本确实注入进了宿主的计划（不是两边都空串），库一侧也得是同一个值
    version = json.loads(
        (SOURCE_ROOT / "res" / "version.json").read_text(encoding="utf-8")
    )["version"]
    assert f'"PI_CLIENT_VERSION": "{version}"' in host_text
    assert library_text == host_text, _first_difference(host, library)
