"""宿主日志的惰性取用。

``host/`` 下的模块原先在模块顶层 ``from app.utils import get_logger``。插件包里不直接
导入宿主模块，SDK（``auto_mas_core``）在导入时就要拉起宿主，所以这里把取 logger 推迟到
第一次真正写日志的时候：模块照旧可以在顶层写 ``logger = get_logger("…")``，logger 名
不变，只有用到时才经 SDK 取宿主的 logger。
"""

from __future__ import annotations

from typing import Any


class _LazyLogger:
    """第一次访问属性时才向宿主取真正的 logger，之后都转发给它。"""

    __slots__ = ("_name", "_logger")

    def __init__(self, name: str) -> None:
        self._name = name
        self._logger: Any = None

    def _resolve(self) -> Any:
        logger = self._logger
        if logger is None:
            from auto_mas_core.utils import get_logger as host_get_logger

            logger = host_get_logger(self._name)
            self._logger = logger
        return logger

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._resolve(), attr)

    def __repr__(self) -> str:
        return f"<惰性 logger {self._name!r}>"


def get_logger(name: str) -> Any:
    """返回一个惰性 logger，用法与宿主 ``app.utils.get_logger`` 返回的对象相同。"""

    return _LazyLogger(name)
