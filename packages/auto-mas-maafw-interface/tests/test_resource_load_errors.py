"""资源包加载失败的说明：MaaFramework 6.0 结构化诊断优先，5.x 照旧刮原生 ERR 行。"""

from __future__ import annotations

from pathlib import Path

from maafw_interface.runner.models import MaaFWResourceFailure
from maafw_interface.runner.resource_failure import (
    NATIVE_LOG_HINT,
    describe_resource_failure,
    describe_resource_load_errors,
)

DUP_LINE = (
    "[2026-10-26 10:00:00.000][ERR][Px1][Tx2][PipelineResMgr.cpp][L180]"
    "[MaaNS::ResourceNS::PipelineResMgr::parse_and_override_once] "
    "key already exists [key=Battle]"
)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    bundle = root / "resource" / "base"
    (bundle / "pipeline").mkdir(parents=True)
    return root, bundle


def _abs(path: Path) -> str:
    return str(path).replace("\\", "/")


def test_model_defaults_and_round_trip() -> None:
    assert MaaFWResourceFailure(kind="load_failed", path="p").errors == []
    failure = MaaFWResourceFailure.model_validate(
        {"kind": "load_failed", "path": "p", "errors": [{"code": "invalid_node"}]}
    )
    assert failure.model_dump(mode="json")["errors"] == [{"code": "invalid_node"}]


def test_node_reference_not_found(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    errors = [
        {
            "code": "node_reference_not_found",
            "file": _abs(bundle / "pipeline" / "main.json"),
            "node": "NodeA",
            "pointer": "/NodeA/next",
            "field": "next",
            "target": "MissingNode",
        }
    ]
    message = describe_resource_failure(
        "load_failed", str(bundle), [], project_root=root, load_errors=errors
    )
    assert message == (
        "MaaFW 运行失败：资源包 resource/base 加载失败：节点「NodeA」的 next "
        "引用了不存在的节点「MissingNode」（resource/base/pipeline/main.json）"
    )


def test_duplicate_node_matches_native_wording(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    first = bundle / "pipeline" / "a.json"
    second = bundle / "pipeline" / "b.json"
    first.write_text('{"Battle": {}}', encoding="utf-8")
    second.write_text('{"Battle": {}}', encoding="utf-8")
    structured = describe_resource_failure(
        "load_failed",
        str(bundle),
        [],
        project_root=root,
        load_errors=[
            {"code": "duplicate_node", "file": _abs(second), "node": "Battle"}
        ],
    )
    native = describe_resource_failure(
        "load_failed",
        str(bundle),
        [
            DUP_LINE,
            "[2026-10-26 10:00:00.001][ERR][Px1][Tx2][PipelineResMgr.cpp][L125]"
            f"[f] parse_config failed [path={_abs(second)}]",
        ],
        project_root=root,
    )
    assert structured == native
    assert "节点「Battle」重复定义（resource/base/pipeline/b.json、" in structured
    assert "resource/base/pipeline/a.json" in structured


def test_invalid_regex_and_extra_count(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    errors = [
        {
            "code": "invalid_regex",
            "file": _abs(bundle / "pipeline" / "ocr.json"),
            "node": "ReadGold",
            "field": "expected",
        },
        {"code": "invalid_node", "node": "Other"},
    ]
    message = describe_resource_load_errors(str(bundle), errors, project_root=root)
    assert message == (
        "MaaFW 运行失败：资源包 resource/base 加载失败：resource/base/pipeline/ocr.json "
        f"里节点「ReadGold」的 expected 不是有效的正则表达式（另有 1 处问题，{NATIVE_LOG_HINT}）"
    )


def test_generic_code_mentions_file_node_field(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    errors = [
        {
            "code": "inference_backend_unavailable",
            "file": _abs(bundle / "model" / "ocr"),
            "node": "ReadGold",
            "field": "recognition",
        }
    ]
    message = describe_resource_load_errors(str(bundle), errors, project_root=root)
    assert message == (
        "MaaFW 运行失败：资源包 resource/base 加载失败：推理后端不可用"
        "（文件 resource/base/model/ocr，节点「ReadGold」，字段 recognition），"
        f"{NATIVE_LOG_HINT}"
    )
    unknown = describe_resource_load_errors(
        str(bundle), [{"code": "brand_new_code"}], project_root=root
    )
    assert unknown == (
        "MaaFW 运行失败：资源包 resource/base 加载失败：加载错误（brand_new_code），"
        f"{NATIVE_LOG_HINT}"
    )


def test_prefers_error_inside_bundle(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    errors = [
        {
            "code": "json_read_failed",
            "file": _abs(root / "resource" / "other" / "x.json"),
        },
        {"code": "json_read_failed", "file": _abs(bundle / "pipeline" / "y.json")},
    ]
    message = describe_resource_load_errors(str(bundle), errors, project_root=root)
    assert message is not None
    assert message.startswith(
        "MaaFW 运行失败：资源包 resource/base 加载失败："
        "resource/base/pipeline/y.json 不是有效的 JSON"
    )


def test_home_path_masked_outside_project(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    home = str(Path.home()).replace("\\", "/")
    errors = [{"code": "path_not_found", "file": f"{home}/elsewhere/res"}]
    message = describe_resource_load_errors(str(bundle), errors, project_root=root)
    assert message is not None
    assert "路径不存在：" in message
    assert home not in message


def test_falls_back_to_native_lines_without_structured(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    native = describe_resource_failure(
        "load_failed", str(bundle), [DUP_LINE], project_root=root
    )
    for load_errors in ((), [], ["junk"], [{"node": "no code"}]):
        assert (
            describe_resource_failure(
                "load_failed",
                str(bundle),
                [DUP_LINE],
                project_root=root,
                load_errors=load_errors,
            )
            == native
        )
    assert "节点「Battle」" in native


def test_missing_kind_ignores_structured(tmp_path: Path) -> None:
    root, bundle = _project(tmp_path)
    message = describe_resource_failure(
        "missing",
        str(bundle),
        [],
        project_root=root,
        load_errors=[{"code": "path_not_found"}],
    )
    assert message.startswith("MaaFW 运行失败：资源目录不存在：resource/base")
