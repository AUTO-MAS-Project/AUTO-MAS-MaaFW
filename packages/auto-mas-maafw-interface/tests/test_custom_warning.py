"""用户可见的外壳私有字段提示，包括升级前保存的磁盘缓存。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from maafw_interface.interface import load_interface_model_cached
from maafw_interface.interface.models import interface_load_warnings


def test_custom_warning_is_visible_after_old_disk_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "interface.json").write_text(
        '{"interface_version": 2, "name": "custom test", "custom": "./custom/custom.json"}',
        encoding="utf-8",
    )
    loaded = load_interface_model_cached(project, force_reload=True)
    assert any("custom" in warning for warning in interface_load_warnings(loaded))

    # 第 7 版格式与新缓存相同，但没有用户可见的 custom 告警。
    caches = list(tmp_path.rglob("*.json"))
    cache = next(path for path in caches if path.parent != project)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["version"] = 7
    payload["warnings"] = []
    cache.write_text(json.dumps(payload), encoding="utf-8")
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment = dict(os.environ, PYTHONPATH=source, PYTHONIOENCODING="utf-8")
    code = (
        "import json; "
        "from maafw_interface.interface import load_interface_model_cached; "
        "from maafw_interface.interface.models import interface_load_warnings; "
        f"model=load_interface_model_cached({str(project)!r}); "
        "print(json.dumps(interface_load_warnings(model)))"
    )
    restarted = subprocess.run(
        [sys.executable, "-c", code],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert any("custom" in warning for warning in json.loads(restarted.stdout))
