"""项目这一块给用户的几句固定话，专项自己判定时要用（MFW 服务化）。

- 三句良性跳过原文与 ``BENIGN_SKIPS``：从项目更新 ``maafw_project_update.host.project_session``
  原文切片抄来，积木仓一条 AST 测试钉住两边相等。项目服务的跳过结果里带的就是这几句，专项照旧
  ``check_result in BENIGN_SKIPS`` 判良性跳过。
- ``describe_open_failure``：打开项目时专项自己那几步（写回、补默认队列、拿锁）出错给用户的话；
  只留非 ``EmbeddedProjectError`` 那一支——项目服务那边的失败已经带着原文回来，专项碰到的只会是
  自己的异常。日志名与原函数相同（``MFW 内置运行``）。
"""

from __future__ import annotations

from ._logging import get_logger

logger = get_logger("MFW 内置运行")

# 运行前检查拿不到本视图预约时的整脚本跳过：项目被同项目的更新 / 编辑页操作暂时占着，
# 不是故障，脚本记「跳过」、发 warning（与调度层「已被其他任务调度器锁定」同一口径）。
SKIP_SWITCHING = (
    "同项目的另一个脚本刚更新了项目，本托管正在切换到新版本，已跳过本次启动，"
    "稍后重新开始即可"
)
SKIP_UPDATING = (
    "这个脚本的项目正在更新（可能是编辑页里的操作），已跳过本次启动，完成后重新开始即可"
)
SKIP_OCCUPIED = (
    "这个脚本的项目正在更新或准备运行环境（可能是编辑页里的操作），已跳过本次启动，"
    "完成后重新开始即可"
)
BENIGN_SKIPS = frozenset({SKIP_SWITCHING, SKIP_UPDATING, SKIP_OCCUPIED})


def describe_open_failure(script_id: str, exc: BaseException) -> str:
    """打开项目时出错给用户的一句话，连同堆栈记一行告警（原函数非 ``EmbeddedProjectError`` 那一支）。"""

    logger.opt(exception=exc).warning(f"MFW 项目导入失败（{script_id}）：{exc}")
    return f"MFW 项目导入失败：{exc}"


__all__ = [
    "BENIGN_SKIPS",
    "SKIP_OCCUPIED",
    "SKIP_SWITCHING",
    "SKIP_UPDATING",
    "describe_open_failure",
]
