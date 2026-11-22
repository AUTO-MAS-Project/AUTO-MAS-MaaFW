from __future__ import annotations

import pytest
from maafw_interface.controller_win32.service import (
    MaaFWWin32ControllerService,
    MaaFWWin32Window,
)
from maafw_interface.embedded_labels import Labels, mxu_option_values
from maafw_interface.interface.models import MaaFWInterface


def _interface(win32: dict | None = None) -> MaaFWInterface:
    return MaaFWInterface.model_validate(
        {
            "interface_version": 2,
            "name": "demo",
            "controller": [
                {
                    "name": "桌面端",
                    "type": "Win32",
                    "win32": win32
                    if win32 is not None
                    else {"class_regex": "Unity", "window_regex": "Game"},
                }
            ],
            "resource": [{"name": "官服", "path": ["resource/base"]}],
            "task": [{"name": "启动", "entry": "Start"}],
            "option": {
                "模式": {"type": "select", "cases": [{"name": "A"}, {"name": "B"}]}
            },
        }
    )


def test_window_rules_match_and_deduplicate() -> None:
    interface = _interface()
    calls: list[int] = []

    def list_windows() -> list[MaaFWWin32Window]:
        calls.append(1)
        return [
            MaaFWWin32Window(1, "UnityWndClass", "Game"),
            MaaFWWin32Window(1, "UnityWndClass", "Game"),
            MaaFWWin32Window(2, "Other", "Game"),
        ]

    matches = MaaFWWin32ControllerService().match_controller_windows(
        interface.controller[0], list_windows
    )
    assert len(matches) == 1
    assert matches[0].controllerName == "桌面端"
    assert calls == [1]


def test_controller_without_window_rules_never_scans() -> None:
    # 原行为：没有窗口规则的控制器直接返回空，根本不扫描
    interface = _interface(win32={})

    def list_windows() -> list[MaaFWWin32Window]:
        raise AssertionError("不该扫描窗口")

    service = MaaFWWin32ControllerService()
    assert service.match_controller_windows(interface.controller[0], list_windows) == []
    assert service.match_controller_windows(interface.controller[0]) == []


def test_controller_with_rules_requires_window_source() -> None:
    interface = _interface()
    with pytest.raises(RuntimeError, match="list_windows"):
        MaaFWWin32ControllerService().match_controller_windows(interface.controller[0])


def test_mxu_choice_conversion_uses_public_helpers() -> None:
    interface = _interface()
    skipped: list[str] = []
    values = mxu_option_values(
        {"模式": {"type": "select", "caseName": "B"}},
        interface.option,
        "设置",
        Labels(interface, None),
        skipped,
    )
    assert values == {"模式": "B"}
    assert skipped == []
