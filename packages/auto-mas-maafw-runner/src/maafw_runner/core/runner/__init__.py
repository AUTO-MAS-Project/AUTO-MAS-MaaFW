from __future__ import annotations

from importlib import import_module

# 惰性导出：只留执行侧的名字。建计划的几个模块（run_plan、models、pipeline_override、
# hotkey、task_selection、plan_transforms）已进解析库 ``maafw_interface.runner``，
# 解析侧的名字从那里取。借还运行环境（``MaaFWRunnerEnvironment`` 等）已挪到宿主侧
# ``maafw_runner.host.environment``，改走 agent 环境的服务（MFW 服务化实施方案 §5），
# ``core`` 不再导出它们；``service`` 只剩建计划的薄壳。
_LAZY_EXPORTS = {
    "MaaFWRunnerService": ".service",
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_LAZY_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    "MaaFWRunnerService",
]
