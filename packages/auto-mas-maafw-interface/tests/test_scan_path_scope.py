"""扫描选项的链接越界降级与缓存恢复。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from maafw_interface.interface import (
    MaaFWInterfaceLoadError,
    load_interface_model_cached,
)


def test_rejected_scan_link_is_not_enumerated_and_recovers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (external / "private.json").write_text("{}", encoding="utf-8")
    link = project / "teams"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(external)],
            capture_output=True,
            check=True,
        )
    else:
        link.symlink_to(external, target_is_directory=True)
    interface = {
        "interface_version": 2,
        "name": "scan test",
        "task": [{"name": "Run", "entry": "Run", "option": ["team"]}],
        "option": {
            "team": {
                "type": "scan_select",
                "scan_dir": "teams",
                "scan_filter": "*.json",
            }
        },
    }
    (project / "interface.json").write_text(json.dumps(interface), encoding="utf-8")
    original_glob = Path.glob
    external_scans = []

    def guarded_glob(path, pattern, *args, **kwargs):
        if path.resolve().is_relative_to(external.resolve()):
            external_scans.append(path)
            raise AssertionError("不能枚举被拒绝的外部目录")
        return original_glob(path, pattern, *args, **kwargs)

    monkeypatch.setattr(Path, "glob", guarded_glob)
    try:
        first = load_interface_model_cached(project)
        assert first.task[0].name == "Run"
        assert first.option["team"].cases == []
        second = load_interface_model_cached(project)
        assert second.option["team"].cases == []
        assert not external_scans
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
    link.mkdir()
    (link / "available.json").write_text("{}", encoding="utf-8")
    restored = load_interface_model_cached(project)
    assert len(restored.option["team"].cases) == 1
    assert restored.option["team"].cases[0].name == "available.json"


def test_import_link_outside_project_is_still_rejected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    (external / "fragment.json").write_text('{"task": []}', encoding="utf-8")
    link = project / "outside"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(external)],
            capture_output=True,
            check=True,
        )
    else:
        link.symlink_to(external, target_is_directory=True)
    (project / "interface.json").write_text(
        '{"interface_version": 2, "import": ["outside/fragment.json"]}',
        encoding="utf-8",
    )
    try:
        with pytest.raises(MaaFWInterfaceLoadError):
            load_interface_model_cached(project)
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()
