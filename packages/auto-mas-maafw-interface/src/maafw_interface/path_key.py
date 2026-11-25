r"""路径当键用之前的归一：去掉 Windows 扩展长度前缀。

Windows 上别的线程正在创建或替换路径上的某级目录时，CPython 3.12 的 ``Path.resolve()``
（``ntpath.realpath``）会交回带 ``\\?\`` 前缀的路径（UNC 路径是 ``\\?\UNC\``）。拿它直接
normcase / casefold / 哈希当键，同一个目录就会算出两个键：interface 的内存缓存键与磁盘缓存文件名
都会偏。「resolve 之后当键」的地方一律经 :func:`resolved_path_str` 取字符串。

本库不依赖别的积木包，所以自己放一份；agent 环境积木（``maafw_agent_env.core.path_key``）与项目更新
积木（``maafw_project_update.core.path_key``）里有同样的两份，三边不互相导入。
"""

from __future__ import annotations

from pathlib import Path

_EXTENDED = "\\\\?\\"
_EXTENDED_UNC = "\\\\?\\UNC\\"


def strip_extended_prefix(path: str) -> str:
    r"""``\\?\C:\x`` 换成 ``C:\x``，``\\?\UNC\srv\share\x`` 换回 ``\\srv\share\x``；别的原样。

    只认盘符与 UNC 两种：``\\?\Volume{…}`` 这类没有对应普通写法的路径不动。
    """

    if path[: len(_EXTENDED_UNC)].upper() == _EXTENDED_UNC:
        return "\\\\" + path[len(_EXTENDED_UNC) :]
    rest = path[len(_EXTENDED) :]
    if (
        path.startswith(_EXTENDED)
        and len(rest) >= 2
        and rest[1] == ":"
        and rest[0].isalpha()
    ):
        return rest
    return path


def resolved_path_str(path: str | Path, *, strict: bool = False) -> str:
    """``str(Path(path).resolve(strict=strict))``，去掉扩展长度前缀。"""

    return strip_extended_prefix(str(Path(path).resolve(strict=strict)))
