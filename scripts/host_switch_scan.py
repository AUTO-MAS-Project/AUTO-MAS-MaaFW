"""按语法树数出宿主里导入这两块库代码的每一处，生成 HOST-SWITCH.md 的清单并验证切换后的写法。

算进来的写法：绝对导入、相对导入（``from ..native.requirement import x``）、「从包导入子模块」
（``from app...core.runner import run_plan``）、惰性导出表与 ``import_module`` 里以字符串写的模块名、
worker 以脚本方式启动时在 runner 目录里按裸名导入（``from run_plan import MaaFWRunPlan``）。
随库搬走的文件自己的导入不算调用方，单列。

用法（工作目录为仓库根）::

    python scripts/host_switch_scan.py --host <宿主检出目录>            # 打印清单
    python scripts/host_switch_scan.py --host ... --write docs/notes/HOST-SWITCH.md               # 写回文档的生成段
    python scripts/host_switch_scan.py --host ... --check docs/notes/HOST-SWITCH.md --verify      # 复核：文档与扫描一致、写法能导入

``--verify`` 在当前解释器里逐条执行「切换后」的导入（需要两个库已安装或在 PYTHONPATH 上）。
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CORE = "app.task.MaaFW.tools.core"
RUNNER = f"{CORE}.runner"
RUNNER_MOVED = (
    "hotkey",
    "models",
    "pipeline_override",
    "plan_transforms",
    "run_plan",
    "task_selection",
)
# 整个模块（或整个包）随库搬走：宿主模块前缀 → 库模块前缀
MOVED = {
    f"{CORE}.native": "maafw_native",
    f"{CORE}.interface": "maafw_interface.interface",
    f"{CORE}.log_redact": "maafw_interface.log_redact",
    **{f"{RUNNER}.{name}": f"maafw_interface.runner.{name}" for name in RUNNER_MOVED},
}
# 只搬一部分的模块：名字 → (库模块, 库里的名字)；不在表里的名字留在宿主
PARTIAL: dict[str, dict[str, tuple[str, str]] | None] = {
    f"{CORE}.controller_win32.service": None,  # 除 _normalize_hwnd 外全进库，见 _partial_target
    f"{CORE}.controller_win32": None,
    "app.task.MaaFW.tools.embedded.shell_instances": {
        "_Labels": ("maafw_interface.embedded_labels", "Labels"),
        "_mxu_option_values": ("maafw_interface.embedded_labels", "mxu_option_values"),
    },
    RUNNER: None,
    CORE: None,
}
RUNNER_PACKAGE_NAMES = {
    "MaaFWDeviceConfig",
    "MaaFWResolvedPath",
    "MaaFWResourceBundlePlan",
    "MaaFWRunPlan",
    "MaaFWRunResult",
    "MaaFWRunnerJobPayload",
    "MaaFWSkippedTaskPlan",
    "MaaFWTaskRunPlan",
    "MaaFWRunPlanError",
    "build_maafw_run_plan",
}
# 运行协议整块留在宿主（归运行积木）：只列出来，不切换
STAYS_NOTE = {f"{CORE}.worker_protocol"}

GENERATED_BEGIN = "<!-- 下面由 scripts/host_switch_scan.py 生成，别手改 -->"
GENERATED_END = "<!-- 生成段结束 -->"


@dataclass
class Edge:
    file: str
    line: int
    kind: str
    module: str  # 宿主一侧被导入的模块（已解析成绝对名）
    names: list[tuple[str, str | None]] = field(default_factory=list)  # (名字, as 别名)
    original: str = ""


def module_name(root: Path, path: Path) -> tuple[str, bool]:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def is_module(root: Path, dotted: str) -> bool:
    base = root.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def resolve_relative(
    current: str, is_package: bool, level: int, module: str | None
) -> str:
    package = current if is_package else current.rpartition(".")[0]
    parts = package.split(".")
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    base = ".".join(parts)
    return f"{base}.{module}" if module else base


def moved_target(module: str) -> str | None:
    for prefix, target in MOVED.items():
        if module == prefix or module.startswith(prefix + "."):
            return target + module[len(prefix) :]
    return None


def is_moved_file(module: str) -> bool:
    return moved_target(module) is not None


def touches(module: str) -> bool:
    return moved_target(module) is not None or module in PARTIAL or module in STAYS_NOTE


def scan_file(root: Path, path: Path) -> list[Edge]:
    current, is_package = module_name(root, path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(root).as_posix()
    runner_dir = rel.startswith("app/task/MaaFW/tools/core/runner/")
    edges: list[Edge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if touches(alias.name):
                    edges.append(
                        Edge(
                            rel,
                            node.lineno,
                            "import",
                            alias.name,
                            [],
                            ast.unparse(node),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                module = resolve_relative(current, is_package, node.level, node.module)
                kind = "相对导入"
            elif (
                runner_dir and node.module and node.module.split(".")[0] in RUNNER_MOVED
            ):
                module = f"{RUNNER}.{node.module}"
                kind = "脚本方式裸名导入"
            else:
                module = node.module or ""
                kind = "绝对导入"
            names = [(alias.name, alias.asname) for alias in node.names]
            submodules = [
                (name, asname)
                for name, asname in names
                if is_module(root, f"{module}.{name}") and touches(f"{module}.{name}")
            ]
            plain = [item for item in names if item not in submodules]
            for name, asname in submodules:
                edges.append(
                    Edge(
                        rel,
                        node.lineno,
                        "从包导入子模块",
                        f"{module}.{name}",
                        [("*module*", asname or name)],
                        ast.unparse(node),
                    )
                )
            if plain and touches(module):
                edges.append(
                    Edge(rel, node.lineno, kind, module, plain, ast.unparse(node))
                )
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                target = value
                attr = None
                if isinstance(target, ast.Tuple) and target.elts:
                    if len(target.elts) > 1 and isinstance(
                        target.elts[1], ast.Constant
                    ):
                        attr = target.elts[1].value
                    target = target.elts[0]
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(target, ast.Constant)
                    and isinstance(target.value, str)
                    and target.value.startswith(".")
                ):
                    level = len(target.value) - len(target.value.lstrip("."))
                    module = resolve_relative(
                        current, is_package, level, target.value[level:] or None
                    )
                    if touches(module):
                        edges.append(
                            Edge(
                                rel,
                                key.lineno,
                                "惰性导出表（字符串模块名）",
                                module,
                                [(attr or key.value, None)],
                                f'"{key.value}": {ast.unparse(value)}',
                            )
                        )
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if (
                name == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                raw = node.args[0].value
                if isinstance(raw, str) and not raw.startswith("."):
                    if touches(raw):
                        edges.append(
                            Edge(
                                rel,
                                node.lineno,
                                "import_module 字符串",
                                raw,
                                [],
                                ast.unparse(node),
                            )
                        )
    return edges


def _partial_target(module: str, name: str) -> tuple[str, str] | None:
    if module == f"{CORE}.controller_win32.service":
        if name == "_normalize_hwnd":
            return None
        return ("maafw_interface.controller_win32.service", name)
    if module == f"{CORE}.controller_win32":
        return ("maafw_interface.controller_win32", name)
    if module == RUNNER:
        return (
            ("maafw_interface.runner", name) if name in RUNNER_PACKAGE_NAMES else None
        )
    if module == CORE:
        return ("maafw_interface", name) if name == "MaaFWInterfaceService" else None
    table = PARTIAL.get(module) or {}
    return table.get(name)


def targets(edge: Edge) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """切换后的 (库模块, [(库里的名字, 别名)])；名字留在宿主的不出现。空表 = 整条留在宿主。"""

    if edge.module in STAYS_NOTE:
        return []
    whole = moved_target(edge.module)
    if edge.kind == "从包导入子模块":
        return [(whole, [("*module*", edge.names[0][1])])] if whole else []
    if whole is not None:
        return [(whole, list(edge.names))]
    grouped: dict[str, list[tuple[str, str | None]]] = {}
    for name, asname in edge.names:
        found = _partial_target(edge.module, name)
        if found is None:
            continue
        lib_module, lib_name = found
        alias = asname if asname else (name if lib_name != name else None)
        grouped.setdefault(lib_module, []).append((lib_name, alias))
    return list(grouped.items())


def render(module: str, names: list[tuple[str, str | None]], kind: str) -> str:
    if names and names[0][0] == "*module*":
        parent, _, child = module.rpartition(".")
        alias = names[0][1]
        suffix = f" as {alias}" if alias and alias != child else ""
        return f"from {parent} import {child}{suffix}"
    if kind == "import" or kind == "import_module 字符串":
        return f"import {module}"
    if kind == "惰性导出表（字符串模块名）":
        return f'getattr(import_module("{module}"), "{names[0][0]}")'
    parts = [
        f"{name} as {alias}" if alias and alias != name else name
        for name, alias in names
    ]
    return f"from {module} import {', '.join(parts)}"


def owner(rel: str) -> tuple[str, str]:
    """(分类, 归属)。分类按任务说明 5.5 的三类。"""

    core = "app/task/MaaFW/tools/core/"
    if rel.startswith(core + "agent_env/"):
        return "服务积木与三个专项", "agent 环境"
    if rel.startswith(core + "project_update/"):
        return "服务积木与三个专项", "项目更新"
    if rel.startswith(
        (core + "runner/", core + "runtime_pool/", core + "worker_protocol")
    ):
        return "服务积木与三个专项", "运行"
    if rel.startswith("app/task/MaaFW/"):
        return "服务积木与三个专项", "通用 MFW"
    if rel.startswith("app/task/M9A/"):
        return "服务积木与三个专项", "M9A"
    if rel.startswith("app/task/MSS/"):
        return "服务积木与三个专项", "MSS"
    parts = rel.split("/")
    if len(parts) > 3 and parts[0] == "app" and parts[1] == "task":
        return "内置 MaaEnd 等别的专项", parts[2]
    if rel.startswith("tests/"):
        return "宿主测试", "tests"
    return "宿主核心", parts[1] if len(parts) > 2 else parts[0]


def collect(root: Path) -> tuple[list[Edge], list[Edge], list[str]]:
    callers: list[Edge] = []
    moved_self: list[Edge] = []
    moved_files: list[str] = []
    paths = sorted(
        [
            *(root / "app").rglob("*.py"),
            root / "main.py",
            *(root / "tests").rglob("*.py"),
        ]
    )
    for path in paths:
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        current, _ = module_name(root, path)
        edges = scan_file(root, path)
        if is_moved_file(current):
            moved_files.append(path.relative_to(root).as_posix())
            moved_self.extend(edges)
        else:
            callers.extend(edges)
    return callers, moved_self, moved_files


def build_markdown(root: Path) -> tuple[str, list[str]]:
    callers, moved_self, moved_files = collect(root)
    statements: list[str] = []
    out: list[str] = [GENERATED_BEGIN, ""]
    switch = [edge for edge in callers if edge.module not in STAYS_NOTE]
    out.append(
        f"扫描范围：`{root}` 的 `app/`、`main.py`、`tests/`。调用方导入 {len(switch)} 处"
        f"（其中宿主测试 {sum(1 for e in switch if e.file.startswith('tests/'))} 处），"
        f"随库搬走的文件 {len(moved_files)} 个。"
    )
    out.append("")
    for category in (
        "服务积木与三个专项",
        "内置 MaaEnd 等别的专项",
        "宿主核心",
        "宿主测试",
    ):
        rows = [edge for edge in switch if owner(edge.file)[0] == category]
        out.append(f"### {category}（{len(rows)} 处）")
        out.append("")
        if not rows:
            out.append("（无）")
            out.append("")
            continue
        out.append("| 归属 | 位置 | 写法 | 现在 | 切换后 |")
        out.append("| --- | --- | --- | --- | --- |")
        for edge in sorted(rows, key=lambda e: (owner(e.file)[1], e.file, e.line)):
            goal = targets(edge)
            if goal:
                after = "<br>".join(f"`{render(m, n, edge.kind)}`" for m, n in goal)
                statements.extend(render(m, n, edge.kind) for m, n in goal)
                stays = [
                    name
                    for name, _ in edge.names
                    if name != "*module*"
                    and _partial_target(edge.module, name) is None
                    and moved_target(edge.module) is None
                ]
                if stays:
                    after += "<br>留在宿主：" + "、".join(f"`{n}`" for n in stays)
            else:
                after = "留在宿主（不改）"
            now = edge.original.replace("|", "\\|").replace("\n", " ")
            if len(now) > 160:
                now = now[:157] + "..."
            out.append(
                f"| {owner(edge.file)[1]} | `{edge.file}:{edge.line}` | {edge.kind} | `{now}` | {after} |"
            )
        out.append("")
    stays = [edge for edge in callers if edge.module in STAYS_NOTE]
    out.append(
        f"### 留在宿主、不切换的运行协议（`worker_protocol`，{len(stays)} 处，仅列出）"
    )
    out.append("")
    out.append("| 位置 | 现在 |")
    out.append("| --- | --- |")
    for edge in sorted(stays, key=lambda e: (e.file, e.line)):
        out.append(
            f"| `{edge.file}:{edge.line}` | `{edge.original.replace(chr(10), ' ')[:160]}` |"
        )
    out.append("")
    out.append(
        f"### 随库搬走、宿主删除的文件（{len(moved_files)} 个；它们自己的 {len(moved_self)} 处导入不算调用方）"
    )
    out.append("")
    for rel in moved_files:
        out.append(f"- `{rel}`")
    out.append("")
    out.append(GENERATED_END)
    return "\n".join(out) + "\n", sorted(set(statements))


def verify(statements: list[str]) -> list[str]:
    script = ["import json, sys", "from importlib import import_module", "bad = []"]
    for stmt in statements:
        script.append("try:")
        script.append(f"    {stmt}")
        script.append("except Exception as exc:")
        script.append(f"    bad.append({stmt!r} + ' -> ' + repr(exc))")
    script.append("sys.stdout.reconfigure(encoding='utf-8')")
    script.append("print(json.dumps(bad, ensure_ascii=False))")
    with tempfile.TemporaryDirectory() as workdir:
        # 在空目录里跑，保证导入到的是已安装的库而不是哪棵源码树
        probe = Path(workdir) / "probe.py"
        probe.write_text("\n".join(script), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(probe)],
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    if completed.returncode != 0:
        return [completed.stderr]
    return json.loads(completed.stdout)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host", type=Path, required=True, help="宿主源码根（含 app/）"
    )
    parser.add_argument("--write", type=Path)
    parser.add_argument("--check", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    markdown, statements = build_markdown(args.host.resolve())
    status = 0
    if args.write or args.check:
        doc_path = args.write or args.check
        doc = doc_path.read_text(encoding="utf-8")
        head, _, rest = doc.partition(GENERATED_BEGIN)
        _, _, tail = rest.partition(GENERATED_END)
        new_doc = head + markdown.rstrip("\n") + tail
        if args.write:
            doc_path.write_bytes(new_doc.encode("utf-8"))
            print(f"已写回 {doc_path}")
        elif new_doc != doc:
            print("文档生成段与扫描结果不一致")
            status = 1
        else:
            print("文档生成段与扫描结果一致")
    else:
        print(markdown)
    if args.verify:
        bad = verify(statements)
        print(f"切换后写法 {len(statements)} 条，导入失败 {len(bad)} 条")
        for item in bad:
            print("  ", item)
        status = status or (1 if bad else 0)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
