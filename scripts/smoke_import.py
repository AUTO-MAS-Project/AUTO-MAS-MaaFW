"""逐个导入指定包下的全部模块，并确认没有带出宿主（``app``）和 SDK（``auto_mas_core``）。

用法::

    python -I scripts/smoke_import.py maafw_interface maafw_native maafw_agent_env.core maafw_runner.core

只给不碰宿主的部分：两块库，以及 worker 子进程也要导入的 ``maafw_agent_env.core``、
``maafw_runner.core``。插件类和 ``host`` 下的模块在导入期就要 SDK，而 SDK 自己要宿主，
离开宿主导入不了，不在这里查。

用 ``-I`` 跑，免得把仓库根或当前目录里的源码当成已安装的包。
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback

FORBIDDEN = ("app", "auto_mas_core")


def _walk(root: str) -> list[str]:
    module = importlib.import_module(root)
    names = [root]
    path = getattr(module, "__path__", None)
    if path is not None:
        names.extend(info.name for info in pkgutil.walk_packages(path, prefix=root + "."))
    return names


def main() -> None:
    # Windows 控制台默认代码页打不出中文；-I 下 PYTHONIOENCODING 不生效，这里自己改
    sys.stdout.reconfigure(encoding="utf-8")
    roots = sys.argv[1:]
    if not roots:
        raise SystemExit("至少给一个包名")
    failed: list[tuple[str, str]] = []
    total = 0
    for root in roots:
        try:
            names = _walk(root)
        except Exception:  # noqa: BLE001
            failed.append((root, traceback.format_exc(limit=3)))
            continue
        for name in names:
            total += 1
            try:
                importlib.import_module(name)
            except Exception:  # noqa: BLE001
                failed.append((name, traceback.format_exc(limit=3)))
    leaked = [name for name in FORBIDDEN if name in sys.modules]
    print(f"模块 {total} 个，失败 {len(failed)} 个，带出的宿主模块：{leaked or '无'}")
    for name, error in failed:
        print(f"--- {name}\n{error}")
    if failed or leaked:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
