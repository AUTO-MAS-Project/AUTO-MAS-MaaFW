"""计算两个库的源码导入闭包和向外依赖。"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "_src"
CORE = "app.task.MaaFW.tools.core"
NATIVE_ROOTS = (f"{CORE}.native",)
INTERFACE_ROOTS = (
    f"{CORE}.interface",
    f"{CORE}.runner.run_plan",
    f"{CORE}.runner.pipeline_override",
    f"{CORE}.runner.hotkey",
    f"{CORE}.runner.models",
    f"{CORE}.runner.task_selection",
    f"{CORE}.runner.plan_transforms",
    f"{CORE}.controller_win32.service",
    f"{CORE}.log_redact",
    "app.task.MaaFW.tools.embedded.shell_instances",
)


def module_file(module: str) -> Path | None:
    rel = Path(*module.split("."))
    p = ROOT / rel / "__init__.py"
    if p.is_file():
        return p
    p = ROOT / rel.with_suffix(".py")
    return p if p.is_file() else None


def resolve_relative(module: str, level: int, name: str | None) -> str:
    path = module_file(module)
    if path is None:
        return ""
    package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    parts = package.split(".")
    parts = parts[: len(parts) - level + 1]
    if name:
        parts.append(name)
    return ".".join(parts)


def imports_of(module: str) -> list[str]:
    path = module_file(module)
    if path is None:
        return []
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            target = (
                resolve_relative(module, node.level, node.module)
                if node.level
                else node.module or ""
            )
            if not target:
                continue
            found.append(target)
            for alias in node.names:
                child = f"{target}.{alias.name}"
                if module_file(child) is not None:
                    found.append(child)
    return found


def is_allowed(module: str, roots: tuple[str, ...]) -> bool:
    if any(
        module == root or module.startswith(root + ".")
        for root in roots
        if root.endswith((".native", ".interface"))
    ):
        return True
    return module in roots


def run(kind: str) -> dict[str, object]:
    roots = NATIVE_ROOTS if kind == "native" else INTERFACE_ROOTS
    queue = deque(roots)
    if kind == "native":
        queue.extend(
            f"{NATIVE_ROOTS[0]}.{path.stem}"
            for path in sorted((ROOT / Path(*NATIVE_ROOTS[0].split("."))).glob("*.py"))
            if path.name != "__init__.py"
        )
    seen: set[str] = set()
    outward: dict[str, set[str]] = {}
    files: list[dict[str, str]] = []
    while queue:
        module = queue.popleft()
        if module in seen:
            continue
        seen.add(module)
        path = module_file(module)
        if path is None:
            continue
        files.append({"module": module, "path": path.relative_to(ROOT).as_posix()})
        for target in imports_of(module):
            if target.startswith("__future__"):
                continue
            if target.startswith("app."):
                if is_allowed(target, roots) and module_file(target) is not None:
                    queue.append(target)
                else:
                    outward.setdefault(module, set()).add(target)
            elif target.split(".", 1)[0] not in sys.stdlib_module_names:
                outward.setdefault(module, set()).add(target)
    return {
        "kind": kind,
        "roots": list(roots),
        "files": sorted(files, key=lambda item: item["module"]),
        "outward": [
            {"source": source, "target": target}
            for source in sorted(outward)
            for target in sorted(outward[source])
        ],
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("native", "interface", "all"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    kinds = ("native", "interface") if args.kind == "all" else (args.kind,)
    result = {kind: run(kind) for kind in kinds}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for kind, value in result.items():
        print(f"[{kind}] 文件")
        for item in value["files"]:
            print(f"  {item['module']} -> {item['path']}")
        print(f"[{kind}] 向外的依赖")
        for edge in value["outward"]:
            print(f"  {edge['source']} -> {edge['target']}")


if __name__ == "__main__":
    main()
