from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from maafw_interface.interface import MaaFWInterfaceService, load_interface_model
from maafw_interface.runner.run_plan import build_maafw_run_plan

WALKREF = Path("D:/MAS/test/walkref")
PROJECTS = ["m9a", "maaend", "mra", "starres", "maabbb", "maayys"]


@pytest.mark.parametrize("name", PROJECTS)
def test_real_interface_load_and_preview(name: str) -> None:
    root = WALKREF / name
    interface = load_interface_model(root)
    preview = MaaFWInterfaceService().preview(root)
    assert preview.project["name"] == interface.name
    assert all(isinstance(item, dict) for item in preview.controllers)
    assert preview.tasks


@pytest.mark.parametrize("name", PROJECTS)
def test_real_interface_builds_a_minimal_plan(name: str) -> None:
    root = WALKREF / name
    interface = load_interface_model(root)
    controller = next(
        item for item in interface.controller if item.type in {"Adb", "Win32"}
    )
    resource = next(
        item
        for item in interface.resource
        if not item.controller or controller.name in item.controller
    )
    task = next(
        item
        for item in interface.task
        if (not item.controller or controller.name in item.controller)
        and (not item.resource or resource.name in item.resource)
    )
    plan = build_maafw_run_plan(
        root,
        interface,
        controller_name=controller.name,
        resource_name=resource.name,
        task_ids=[task.name],
        client_version="v9.9.9",
    )
    assert plan.controllerName == controller.name
    assert plan.resourceName == resource.name
    assert plan.tasks
    # 客户端版本由调用方传入，库不自己去找宿主的版本文件
    assert plan.piEnv["PI_CLIENT_VERSION"] == "v9.9.9"


def test_light_modules_do_not_pull_in_parsing_stack() -> None:
    # 运行侧（worker、agent 环境）只要 log_redact 的常量，不该连带加载 pydantic、json5 和解析模块
    code = (
        "import sys, maafw_interface.log_redact\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in ('pydantic', 'json5')"
        " or m.startswith('maafw_interface.interface') or m.startswith('maafw_interface.runner'))\n"
        "print(heavy)\n"
        "raise SystemExit(1 if heavy else 0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
