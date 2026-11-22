"""宿主能力的惰性入口（插件包新写，不是搬来的）。

``host/`` 下的模块在宿主时代顶层就 ``from app.utils import get_logger``、模块级建好 logger。
插件包里宿主的东西只经 SDK（``auto_mas_core``）取，而 ``auto_mas_core`` 一导入就要宿主的
``app`` 包。为了让这些模块在没有宿主的环境里也能导入（打包检查、单元测试），logger 改成
第一次用到时才向 SDK 要：名字、日志去向与搬家前相同。
"""

from __future__ import annotations

from typing import Any


class _LazyLogger:
    """第一次取属性时才调 ``auto_mas_core.utils.get_logger(name)``，之后原样转发。"""

    __slots__ = ("_name", "_logger")

    def __init__(self, name: str) -> None:
        self._name = name
        self._logger: Any = None

    def _resolve(self) -> Any:
        if self._logger is None:
            from auto_mas_core.utils import get_logger as _sdk_get_logger

            self._logger = _sdk_get_logger(self._name)
        return self._logger

    def __getattr__(self, item: str) -> Any:
        return getattr(self._resolve(), item)


def get_logger(name: str) -> Any:
    """与宿主 ``app.utils.get_logger`` 同名同参；返回的对象在第一次使用时才绑定宿主 logger。"""
    return _LazyLogger(name)
