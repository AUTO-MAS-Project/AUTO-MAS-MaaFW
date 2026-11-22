"""建运行计划与预览共用的规则表：哪些任务不可选、哪些任务失败即结束本轮或失败不计、
哪些字符串输入项没填时不回落 default。

规则表是调用方（宿主按脚本类型）给的普通数据，核心不认识具体项目；建计划、展开任务快照
（``runner/task_selection``）与预览（``preview.apply_preview_plan_rules``）收同一份。没有
规则的项目传空表，行为与没有这一层时完全相同。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MaaFWPlanRules:
    """建计划与预览的规则表；各表的键都是任务 ``entry``（``no_default_fallback_inputs`` 除外）。"""

    unselectable: Mapping[str, str] = field(default_factory=dict)
    """不可选任务：entry → 不能选的原因。预览给它们填 ``unselectableReason``；展开任务快照时
    在交给调用方排队列之前剔掉（连同选项），不进计划。"""

    abort_round: Mapping[str, str] = field(default_factory=dict)
    """失败即结束本轮：entry → 失败时报给用户的话，落到计划任务的 ``abortRoundMessage``。"""

    nonfatal: Mapping[str, str] = field(default_factory=dict)
    """失败不计：entry → 失败时接在日志后的说明，落到计划任务的 ``nonFatalMessage``。"""

    no_default_fallback_inputs: frozenset[tuple[str, str]] = frozenset()
    """字符串字段没填时不回落 default 的 input：``(选项名, 字段名)``。建计划时传给覆盖构建，
    预览里把这些字段的 ``default`` 置空。"""

    def to_dict(self) -> dict[str, Any]:
        """转成只含 JSON 值的字典（跨插件服务传它）；``from_dict`` 能无损还原。

        形状：``{"unselectable": {}, "abort_round": {}, "nonfatal": {},
        "no_default_fallback_inputs": [[选项名, 字段名], …]}``，最后一项按字典序排，输出稳定。
        """

        return {
            "unselectable": dict(self.unselectable),
            "abort_round": dict(self.abort_round),
            "nonfatal": dict(self.nonfatal),
            "no_default_fallback_inputs": [
                [option, name]
                for option, name in sorted(self.no_default_fallback_inputs)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> MaaFWPlanRules:
        """``to_dict`` 的逆。缺的键按空表；不认识的键忽略；形状不对抛 ``ValueError``。"""

        source = data or {}
        if not isinstance(source, Mapping):
            raise ValueError("规则表必须是字典")

        def table(key: str) -> dict[str, str]:
            raw = source.get(key) or {}
            if not isinstance(raw, Mapping):
                raise ValueError(f"规则表的 {key} 必须是字典")
            result: dict[str, str] = {}
            for entry, text in raw.items():
                if not isinstance(entry, str) or not isinstance(text, str):
                    raise ValueError(f"规则表的 {key} 只能是字符串到字符串")
                result[entry] = text
            return result

        pairs: set[tuple[str, str]] = set()
        raw_pairs = source.get("no_default_fallback_inputs") or []
        if isinstance(raw_pairs, (str, bytes)) or not isinstance(raw_pairs, Iterable):
            raise ValueError("规则表的 no_default_fallback_inputs 必须是列表")
        for pair in raw_pairs:
            if (
                isinstance(pair, (str, bytes))
                or not isinstance(pair, Iterable)
                or len(items := tuple(pair)) != 2
                or not all(isinstance(item, str) for item in items)
            ):
                raise ValueError(
                    "规则表的 no_default_fallback_inputs 每项必须是 [选项名, 字段名]"
                )
            pairs.add((items[0], items[1]))
        return cls(
            unselectable=table("unselectable"),
            abort_round=table("abort_round"),
            nonfatal=table("nonfatal"),
            no_default_fallback_inputs=frozenset(pairs),
        )


EMPTY_PLAN_RULES = MaaFWPlanRules()
"""没有任何规则（通用项目）。"""


__all__ = ["EMPTY_PLAN_RULES", "MaaFWPlanRules"]
