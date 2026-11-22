"""MFW 运行计划变换（周期任务过滤与记账、重试剔除）的纯函数回归。"""

from __future__ import annotations

from datetime import datetime, timezone

from maafw_interface.runner.models import (
    MaaFWResourceBundlePlan,
    MaaFWRunPlan,
    MaaFWTaskRunPlan,
)
from maafw_interface.runner.plan_transforms import (
    PERIOD_DONE_REASONS,
    PERIOD_DUPLICATE_REASON,
    RETRY_SKIP_REASON,
    MaaFWPeriodLimits,
    filter_period_once_tasks,
    record_period_completions,
    skip_tasks_completed_this_run,
)


def _plan(*tasks: tuple[str, str]) -> MaaFWRunPlan:
    return MaaFWRunPlan(
        path="project",
        projectName="demo",
        controllerName="安卓端",
        controllerType="Adb",
        resourceName="官服",
        resource=MaaFWResourceBundlePlan(name="官服", paths=[], hash="0"),
        tasks=[MaaFWTaskRunPlan(name=name, entry=entry) for name, entry in tasks],
    )


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_period_filter_rolls_over_day_week_month_at_utc_plus_4() -> None:
    limits = MaaFWPeriodLimits.of(daily=["日常"], weekly=["周常"], monthly=["月常"])
    plan = _plan(
        ("日常", "Daily"),
        ("周常", "Weekly"),
        ("月常", "Monthly"),
        ("日常", "Daily"),
        ("普通", "Plain"),
    )
    # 2026-05-31 是周日、月末。UTC 19:30 = UTC+4 23:30，仍是 5 月 31 日这一天、ISO 第 22 周。
    sunday_night = _utc(2026, 5, 31, 19, 30)
    empty: dict[str, dict[str, str]] = {}

    first = filter_period_once_tasks(plan, limits, empty, sunday_night)
    assert [task.name for task in first.tasks] == ["日常", "周常", "月常", "普通"]
    assert [(s.name, s.reason) for s in first.skippedTasks] == [
        ("日常", PERIOD_DUPLICATE_REASON)
    ]

    records = record_period_completions(
        empty, limits, ["日常", "周常", "月常", "普通", "日常"], sunday_night
    )
    assert records == {
        "daily": {"日常": "2026-05-31"},
        "weekly": {"周常": "2026-W22"},
        "monthly": {"月常": "2026-05"},
    }
    assert empty == {}
    # 同一周期再记一次，记录不变（调用方据此不写配置）
    assert record_period_completions(records, limits, ["日常"], sunday_night) == (
        records
    )

    # UTC 19:59 仍是 UTC+4 的 23:59：三种周期都已完成
    same_period = filter_period_once_tasks(
        plan, limits, records, _utc(2026, 5, 31, 19, 59)
    )
    assert [task.name for task in same_period.tasks] == ["普通"]
    assert [s.reason for s in same_period.skippedTasks] == [
        PERIOD_DONE_REASONS["daily"],
        PERIOD_DONE_REASONS["weekly"],
        PERIOD_DONE_REASONS["monthly"],
        PERIOD_DONE_REASONS["daily"],
    ]

    # UTC 20:30 在 UTC 下还是 5 月 31 日周日，按 UTC+4 已是 6 月 1 日周一：日、周、月同时翻篇
    new_month = filter_period_once_tasks(
        plan, limits, records, _utc(2026, 5, 31, 20, 30)
    )
    assert [task.name for task in new_month.tasks] == ["日常", "周常", "月常", "普通"]

    # 6 月 1 日记过之后，6 月 3 日（周三）只有每日任务翻篇
    june_records = record_period_completions(
        records, limits, ["日常", "周常", "月常"], _utc(2026, 5, 31, 20, 30)
    )
    wednesday = filter_period_once_tasks(
        plan, limits, june_records, _utc(2026, 6, 3, 8, 0)
    )
    assert [task.name for task in wednesday.tasks] == ["日常", "普通"]
    assert [(s.name, s.reason) for s in wednesday.skippedTasks] == [
        ("周常", PERIOD_DONE_REASONS["weekly"]),
        ("月常", PERIOD_DONE_REASONS["monthly"]),
        ("日常", PERIOD_DUPLICATE_REASON),
    ]


def test_retry_skips_completed_allowed_tasks_but_reruns_duplicates() -> None:
    plan = _plan(
        ("作战", "Fight"),
        ("奖励", "Award"),
        ("作战", "Fight"),
        ("日常", "Daily"),
        ("商店", "Shop"),
    )
    entries = frozenset({"Fight", "Award", "Shop"})

    outcome = skip_tasks_completed_this_run(plan, ["作战", "奖励", "日常"], entries)

    # 奖励：允许剔、已完成、只有一份 → 剔掉；作战有两份 → 分不清哪份完成，全部重跑；
    # 日常不在允许名单里 → 照跑；商店没完成过 → 照跑
    assert [task.name for task in outcome.plan.tasks] == [
        "作战",
        "作战",
        "日常",
        "商店",
    ]
    assert [(s.name, s.entry, s.reason) for s in outcome.plan.skippedTasks] == [
        ("奖励", "Award", RETRY_SKIP_REASON)
    ]
    assert outcome.rerun_duplicates == ["作战", "作战"]
    assert len(plan.tasks) == 5 and plan.skippedTasks == []

    # 没有允许剔除的 entry 时原样返回
    assert skip_tasks_completed_this_run(plan, ["奖励"], frozenset()).plan is plan
