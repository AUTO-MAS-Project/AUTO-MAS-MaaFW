from __future__ import annotations

import ast
import sys
from pathlib import Path

import maafw_native

# 扫实际导入的那份包（装成 wheel 时就是 site-packages 里的那份），不是源码树
SRC = Path(maafw_native.__file__).parent
ALLOWED = {"packaging"}


def test_no_host_or_undeclared_imports() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".", 1)[0]
                if name == "app" or name.startswith("app."):
                    violations.append(f"{path}:{node.lineno}: {name}")
                elif (
                    root not in sys.stdlib_module_names
                    and root not in ALLOWED
                    and root != ""
                ):
                    violations.append(f"{path}:{node.lineno}: {name}")
    assert not violations, "native 导入越界：\n" + "\n".join(violations)
