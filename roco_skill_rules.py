#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从技能描述里读先手、应对和防御减伤等规则。

这些规则原始数据里没有单独的字段，只能从中文描述中提取。这里集中处理，
避免网页显示、对局日志和伤害推断各写一份、慢慢出现差异。
"""

from __future__ import annotations

import re

PRIORITY_PATTERN = re.compile(r"先手([+-]\d+)")
DAMAGE_REDUCTION_PATTERN = re.compile(r"减伤(\d+)%")

# 带条件的先手不自动套用，只提示条件。
CONDITIONAL_PRIORITY_MARKERS = (
    ("位于1号位时", "位于1号位时"),
    ("天气为沙暴时", "沙暴天气时"),
)

COUNTER_TAGS = ("应对攻击", "应对状态", "应对防御")
ACTION_CATEGORIES = ("攻击", "防御", "状态")

# 这些防御技能虽然有减伤百分比，但还有会改变目标、伤害公式或“保留 1 血”
# 等第一版没有建模的效果，因此暂不用于推断。
_UNSUPPORTED_DEFENSE_SKILLS = {
    "血气",
    "无畏之心",
    "硬门",
    "听桥",
    "镜像反射",
    "遁地",
    "泡沫幻影",
    "吓退",
    "无风",
    "掩护",
    "集中",
    "虚假破产",
}


def skill_priority(description):
    """返回 (先手值, 条件说明)。

    普通技能是 0；“先手+1/-1”直接给出；“敌方先手-1”“下一次行动获得
    先手+1”不是本技能的先手，不计算；带位置或天气条件的先手只提示。
    """
    text = str(description or "")
    clean = re.sub(r"敌方先手[+-]\d+", "", text)
    clean = re.sub(r"获得先手[+-]\d+", "", clean)
    match = PRIORITY_PATTERN.search(clean)
    if not match:
        return 0, None

    value = int(match.group(1))
    for marker, label in CONDITIONAL_PRIORITY_MARKERS:
        if marker in text:
            return 0, f"{label}先手{value:+d}"
    return value, None


def counter_tags(description):
    """返回技能描述里写到的应对类型，例如 {'攻击'}。"""
    text = str(description or "")
    return {
        tag.removeprefix("应对")
        for tag in COUNTER_TAGS
        if tag in text
    }


def damage_reduction_percent(description):
    """读取“减伤 70%”里的 70；没有就返回 None。"""
    match = DAMAGE_REDUCTION_PATTERN.search(str(description or ""))
    return int(match.group(1)) if match else None


def has_variable_damage_reduction(description):
    text = str(description or "")
    return any(
        marker in text
        for marker in ("额外减伤", "每有", "每层", "伤害减少量")
    )


def defense_damage_plan(skill_name, description):
    """判断一个防御技能能不能用于第一版伤害推断。

    返回 {"reduction": 百分比或 None, "supported": bool, "reason": ...}。
    """
    text = str(description or "")
    reduction = damage_reduction_percent(text)
    if reduction is None:
        return {
            "reduction": None,
            "supported": False,
            "reason": "这个防御技能没有写固定减伤百分比。",
        }
    if has_variable_damage_reduction(text):
        return {
            "reduction": reduction,
            "supported": False,
            "reason": "这个防御技能的减伤百分比会随条件变化，第一版暂不推断。",
        }
    if skill_name in _UNSUPPORTED_DEFENSE_SKILLS:
        return {
            "reduction": reduction,
            "supported": False,
            "reason": f"防御技能“{skill_name}”还有第一版未建模的特殊效果。",
        }
    if "造成" in text and "威力" in text:
        return {
            "reduction": reduction,
            "supported": False,
            "reason": "这个防御技能会额外造成伤害，第一版暂不推断。",
        }
    if any(marker in text for marker in ("脱离", "返场", "替换入场")):
        return {
            "reduction": reduction,
            "supported": False,
            "reason": "这个防御技能带有离场/换人效果，第一版暂不推断。",
        }
    if any(marker in text for marker in ("保留1生命", "致命伤害")):
        return {
            "reduction": reduction,
            "supported": False,
            "reason": "这个防御技能会改变击倒规则，第一版暂不推断。",
        }
    if "变为被应对的技能" in text:
        return {
            "reduction": reduction,
            "supported": False,
            "reason": "这个防御技能会复制对方技能，第一版暂不推断。",
        }
    return {"reduction": reduction, "supported": True, "reason": None}


def defense_pre_damage_layers(skill_name, damage_class):
    """纤维化/虚化在本次攻击结算前提供的防御层数。

    物攻看物防，魔攻看魔防；这两个技能分别 +70%（7 层）。其他防御
    技能返回空字典。
    """
    if skill_name == "纤维化" and damage_class == "物攻":
        return {"def": 7}
    if skill_name == "虚化" and damage_class == "魔攻":
        return {"spd": 7}
    return {}


def counter_happened(our_category, our_description, opp_category, opp_description):
    """判断一回合是否发生应对。

    our_category/opp_category 是“攻击/防御/状态”；聚能按“状态”处理。
    切换或空行动传 None。
    """
    if not our_category or not opp_category:
        return False
    our_tags = counter_tags(our_description)
    opp_tags = counter_tags(opp_description)
    return opp_category in our_tags or our_category in opp_tags
