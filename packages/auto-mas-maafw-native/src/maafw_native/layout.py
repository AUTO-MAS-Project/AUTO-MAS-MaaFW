"""MFW 在 AUTO-MAS 工作目录下的目录布局常量（只用标准库）。

agent 环境、worker 与宿主接缝（``tools/embedded/embedded_project``）都要用；项目更新仍是
这些目录唯一的写入方。
"""

from __future__ import annotations

import uuid
from pathlib import Path

#: 项目子进程（agent 与给它准备环境的 pip）写 Python 字节码缓存的目录名，放在项目根下。
#: 不设的话 pyc 会散进项目自带的 ``python/Lib`` 与 ``agent/``（M9A 一轮 2000 多个、15 MB），
#: 副本从此和导入时对不上；``PYTHONDONTWRITEBYTECODE`` 不是替代——那会让每次启动多 1–2 s 编译。
PROJECT_PYCACHE_DIR_NAME = ".pycache"

#: 内嵌副本根目录（相对 AUTO-MAS 工作目录），副本目录名是托管 uuid 去掉连字符的前 12 位
#: （``embedded_project.embedded_copy_dir_name``）。名字这么短是为了路径长度：pyc 前缀树里
#: 项目根出现两遍，M9A 自带 site-packages 最深 75 字符，``data/maafw_projects/<完整 uuid>``
#: 在每个 Windows 用户的安装目录（%LOCALAPPDATA%\Programs\AUTO-MAS）下就撞 MAX_PATH。
EMBEDDED_COPIES_DIR_PARTS = ("data", "mfw")
#: 副本根下的两个簿记目录：不可变项目载荷（``<谱系>/<版本>-<hash>``）与视图切换 journal。
#: 名字以点开头，不是副本目录名的形状，启动期孤儿清理不会把它们当副本删。
EMBEDDED_PAYLOADS_DIR_NAME = ".payloads"
EMBEDDED_SWITCH_DIR_NAME = ".switch"
#: 视图目录名的长度：托管 uuid 去掉连字符后取这么多位。
VIEW_DIR_NAME_LENGTH = 12


def view_dir(script_id: str, base: Path | None = None) -> Path:
    """托管的视图目录（有效项目根）：``<base>/data/mfw/<托管 uuid 去连字符的前 12 位>``。

    ``base`` 缺省是当前工作目录；不做 ``resolve()``。与项目更新的 ``embedded_project_dir``
    （``resolve_maafw_project_root`` 同它）是同一算法；托管 ID 为空或不是 uuid 形状时抛
    ``ValueError``（文案与项目更新的 ``EmbeddedProjectError`` 相同），别让别的东西拼进路径。
    """

    normalized = str(script_id or "").strip()
    if not normalized:
        raise ValueError("内嵌副本需要 scriptId")
    try:
        name = uuid.UUID(normalized).hex[:VIEW_DIR_NAME_LENGTH]
    except ValueError as exc:
        raise ValueError(f"scriptId 不是合法的 uuid：{script_id}") from exc
    return (base if base is not None else Path.cwd()).joinpath(
        *EMBEDDED_COPIES_DIR_PARTS, name
    )


__all__ = [
    "EMBEDDED_COPIES_DIR_PARTS",
    "EMBEDDED_PAYLOADS_DIR_NAME",
    "EMBEDDED_SWITCH_DIR_NAME",
    "PROJECT_PYCACHE_DIR_NAME",
    "VIEW_DIR_NAME_LENGTH",
    "view_dir",
]
