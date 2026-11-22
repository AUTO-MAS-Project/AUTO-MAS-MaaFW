from __future__ import annotations

from pathlib import Path

from maafw_native.pe import detect_pe_architecture
from maafw_native.requirement import resolve_project_maafw_requirement
from maafw_native.requirements_file import read_requirements_file
from maafw_native.versions import (
    exact_version_of,
    normalize_maafw_requirement,
    normalize_version,
)

WALKREF = Path("D:/MAS/test/walkref")


def test_version_and_requirement_normalization() -> None:
    assert normalize_version("v5.13.0-beta.2") == "5.13.0b2"
    assert exact_version_of("maafw==5.13.0") == "5.13.0"
    assert exact_version_of("maafw>=5.12,<6") is None
    assert normalize_maafw_requirement("5.13.0") == "maafw==5.13.0"


def test_requirements_file_reads_project_style_includes(tmp_path: Path) -> None:
    (tmp_path / "nested.txt").write_text("maafw==5.13.0\n", encoding="utf-8")
    root = tmp_path / "requirements.txt"
    root.write_text("-r nested.txt\njson5>=0.14 # comment\n", encoding="utf-8")
    parsed = read_requirements_file(root)
    assert parsed is not None
    assert parsed.requirements == ["maafw==5.13.0", "json5>=0.14"]


def test_pe_architecture_uses_real_walkref_dll() -> None:
    dlls = sorted(WALKREF.rglob("MaaFramework.dll")) if WALKREF.is_dir() else []
    assert dlls, "walkref 中没有 MaaFramework.dll 夹具"
    assert detect_pe_architecture(dlls[0]) in {"x86", "x64", "arm64"}


def test_project_requirement_prefers_bundled_version(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("maafw>=5.12,<6\n", encoding="utf-8")
    result = resolve_project_maafw_requirement(tmp_path)
    assert result is not None
