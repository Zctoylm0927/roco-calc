#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""6 对 6 队伍的范围推断。

和单只精灵版（roco_analysis.py）的区别：

- 我方最多 6 只，性格/天分/当前生命全部已知；
- 对方最多 6 只，每只单独维护一套「性格 + 天分」候选；
- 同一条战斗记录只影响它指向的那一只对方精灵，不会影响其他位置；
- 支持「我方打对方」和「对方打我方」两种伤害记录；
- 对方生命用显示百分比记录，可以额外填写实际变化量；
- 我方生命用具体数字记录，不使用百分比。

单只精灵的旧接口保持不变，本模块只新增队伍接口。
"""

from __future__ import annotations

import math
from array import array
from functools import lru_cache

import roco_analysis as ra
import roco_calc as rc

MAX_TEAM_SIZE = 6
MAX_OUR_SKILLS = 4
DEFAULT_LEVEL = 60


class TeamAnalysisError(ra.AnalysisError):
    """队伍分析的输入或记录不合法。"""


# ---------------------------------------------------------------------------
# 基础校验
# ---------------------------------------------------------------------------

_OUR_SIDE_NAMES = {"our", "ours", "us", "我方", "我们", "我"}
_THEIR_SIDE_NAMES = {
    "theirs", "their", "them", "opponent", "对方", "敌方", "对面",
}


def _normalize_side(value, label="阵营"):
    if not isinstance(value, str):
        raise TeamAnalysisError(f"{label}必须是 our（我方）或 theirs（对方）。")
    text = value.strip().lower()
    if text in _OUR_SIDE_NAMES:
        return "our"
    if text in _THEIR_SIDE_NAMES:
        return "theirs"
    raise TeamAnalysisError(f"{label}只能是 our（我方）或 theirs（对方）。")


def _int_field(
    value, label, minimum=None, maximum=None, *, required=True, default=None
):
    if value is None:
        if required:
            raise TeamAnalysisError(f"{label}必须填写。")
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeamAnalysisError(f"{label}必须是整数。")
    if minimum is not None and value < minimum:
        raise TeamAnalysisError(f"{label}不能小于 {minimum}。")
    if maximum is not None and value > maximum:
        raise TeamAnalysisError(f"{label}不能大于 {maximum}。")
    return value


def _slot_index(value, label):
    if value is None:
        value = 0
    return _int_field(value, label, 0, MAX_TEAM_SIZE - 1)


def _pet_ref(value, label):
    """接受 "水灵" 或 {"name": "水灵", "form": "..."}。"""
    if isinstance(value, str):
        name = value.strip()
        form = None
    elif isinstance(value, dict):
        name = value.get("name")
        form = value.get("form")
        if not isinstance(name, str):
            raise TeamAnalysisError(f"{label}必须填写名称。")
        name = name.strip()
        if form is not None and not isinstance(form, str):
            raise TeamAnalysisError(f"{label}的形态必须是文本。")
        form = form or None
    else:
        raise TeamAnalysisError(
            f"{label}必须写成名称，或写成包含 name 的字典。"
        )
    if not name:
        raise TeamAnalysisError(f"{label}必须填写名称。")
    return {"name": name, "form": form}


def _skill_entries(raw, label, max_count=None):
    """把技能列表统一成 [{"name":..., "power":..., "hits":...}]。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TeamAnalysisError(f"{label}必须是列表。")
    if max_count is not None and len(raw) > max_count:
        raise TeamAnalysisError(f"{label}最多只能有 {max_count} 个。")

    entries = []
    names = set()
    for position, item in enumerate(raw, 1):
        extra = {}
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            value = item.get("name")
            if not isinstance(value, str):
                raise TeamAnalysisError(
                    f"{label}第 {position} 个技能必须填写名称。"
                )
            name = value.strip()
            if item.get("power") is not None:
                if isinstance(item["power"], bool) or not isinstance(
                    item["power"], (int, float)
                ):
                    raise TeamAnalysisError(
                        f"{label}第 {position} 个技能的威力必须是数字。"
                    )
                extra["power"] = item["power"]
            if item.get("hits") is not None:
                extra["hits"] = _int_field(
                    item["hits"],
                    f"{label}第 {position} 个技能的连击",
                    1,
                )
        else:
            raise TeamAnalysisError(
                f"{label}第 {position} 个技能必须写成名称或字典。"
            )
        if not name:
            raise TeamAnalysisError(f"{label}第 {position} 个技能没有名称。")
        if name in names:
            raise TeamAnalysisError(f"{label}里技能“{name}”重复了。")
        try:
            rc.find_skill(name)
        except rc.RocoCalcError as exc:
            raise TeamAnalysisError(
                f"{label}第 {position} 个技能：{exc}"
            ) from exc
        names.add(name)
        entry = {"name": name}
        entry.update(extra)
        entries.append(entry)
    return entries


def _empty_slot(slot):
    return slot is None or slot == {} or (
        isinstance(slot, dict) and slot.get("pet") in (None, "")
    )


def _team_list(state, key, label):
    raw = state.get(key, [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise TeamAnalysisError(f"{label}必须是列表。")
    if len(raw) > MAX_TEAM_SIZE:
        raise TeamAnalysisError(
            f"{label}最多 {MAX_TEAM_SIZE} 个位置，现在有 {len(raw)} 个。"
        )
    return raw


def _build_our_slot(raw, index, level):
    label = f"我方第 {index + 1} 只精灵"
    ref = _pet_ref(raw.get("pet"), label)
    try:
        panel = rc.build_panel(
            ref["name"],
            form=ref["form"],
            nature=raw.get("nature"),
            talents=raw.get("talents"),
            level=level,
        )
        buffs = rc.normalize_buffs(raw.get("buffs"))
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(f"{label}：{exc}") from exc

    skills = _skill_entries(
        raw.get("skills"), f"{label}的技能", MAX_OUR_SKILLS
    )
    starfall = _int_field(
        raw.get("starfall_layers", 0),
        f"{label}的星陨层数",
        0,
        rc.STARFALL_LAYER_LIMIT,
    )
    max_hp = panel["stats"]["hp"]
    current_hp = _int_field(
        raw.get("current_hp"),
        f"{label}的当前生命",
        0,
        max_hp,
        required=False,
        default=max_hp,
    )
    return {
        "slot": index,
        "configured": True,
        "pet": panel["pet"],
        "panel": panel,
        "max_hp": max_hp,
        "hp_lo": current_hp,
        "hp_hi": current_hp,
        "skills": skills,
        "buffs": buffs,
        "starfall_layers": starfall,
    }


@lru_cache(maxsize=None)
def _stat_values(number, form, level, key):
    """每个候选在该项属性上的取值，按候选编号排列。"""
    pet = rc.find_pet(number, form)
    model = ra._model_for(pet, level)
    values = array("I", [0]) * model.total
    for value, bits in model.value_bits[key].items():
        for index in _iter_bits(bits):
            values[index] = value
    return values


def _build_opponent_slot(raw, index, level):
    label = f"对方第 {index + 1} 只精灵"
    ref = _pet_ref(raw.get("pet"), label)
    try:
        pet = rc.find_pet(ref["name"], ref["form"])
        model = ra._model_for(pet, level)
        buffs = rc.normalize_buffs(raw.get("buffs"))
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(f"{label}：{exc}") from exc

    skills = _skill_entries(raw.get("skills"), f"{label}的技能")
    starfall = _int_field(
        raw.get("starfall_layers", 0),
        f"{label}的星陨层数",
        0,
        rc.STARFALL_LAYER_LIMIT,
    )
    max_hp_values = _stat_values(pet["number"], pet["form"], level, "hp")
    return {
        "slot": index,
        "configured": True,
        "pet": pet,
        "model": model,
        "bits": model.mask,
        "hp_lo": array("I", max_hp_values),
        "hp_hi": array("I", max_hp_values),
        "hp_touched": False,
        "skills": skills,
        "observed_skills": [],
        "buffs": buffs,
        "starfall_layers": starfall,
    }


def _build_team(state, key, label, level, our):
    raw = _team_list(state, key, label)
    slots = []
    for index in range(MAX_TEAM_SIZE):
        item = raw[index] if index < len(raw) else None
        if _empty_slot(item):
            slots.append(None)
            continue
        if not isinstance(item, dict):
            raise TeamAnalysisError(f"{label}第 {index + 1} 个位置必须是字典。")
        if our:
            slots.append(_build_our_slot(item, index, level))
        else:
            slots.append(_build_opponent_slot(item, index, level))
    return slots


# ---------------------------------------------------------------------------
# 生命百分比区间
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _hp_interval(max_hp, percent, mode):
    """最大生命为 max_hp 时，显示为 percent 的剩余生命范围。"""
    low = None
    high = None
    for value in range(max_hp + 1):
        if ra._rounded_percent(value, max_hp, mode) == percent:
            if low is None:
                low = value
            high = value
    if low is None:
        return None
    return low, high


# 每个字节里哪些位是 1。逐字节查表比反复操作几万位的大整数快得多。
_BYTE_BITS = tuple(
    tuple(offset for offset in range(8) if byte >> offset & 1)
    for byte in range(256)
)


def _iter_bits(bits):
    """按编号从小到大列出位图里所有为 1 的候选编号。"""
    data = bits.to_bytes((bits.bit_length() + 7) // 8, "little")
    for byte_index, byte in enumerate(data):
        base = byte_index << 3
        for offset in _BYTE_BITS[byte]:
            yield base + offset


# ---------------------------------------------------------------------------
# 伤害模拟
# ---------------------------------------------------------------------------


def _simulate_damage(
    our_panel,
    opponent_pet,
    level,
    skill,
    opponent_is_defender,
    stat_key,
    value,
    weather,
    attacker_buffs,
    defender_buffs,
    starfall_layers,
    options,
):
    """把对方某一项属性设成 value，模拟一次伤害。

    对方当守方时，其他属性与伤害无关；对方当攻方时，只有攻击项参与
    伤害公式。因此其余项统一填 1，不影响结果。
    """
    stats = {key: 1 for key in rc.STAT_KEYS}
    stats[stat_key] = value
    if opponent_is_defender:
        attacker = our_panel
        defender = {"pet": opponent_pet, "level": level, "stats": stats}
    else:
        attacker = {"pet": opponent_pet, "level": level, "stats": stats}
        defender = our_panel
    result = rc.calculate_damage(
        attacker,
        defender,
        skill,
        weather=weather,
        attacker_buffs=attacker_buffs,
        defender_buffs=defender_buffs,
        starfall_layers=starfall_layers,
        **options,
    )
    return result["total_damage"]


def _damage_map(
    our_panel,
    opponent_pet,
    level,
    skill,
    opponent_is_defender,
    stat_key,
    values,
    weather,
    attacker_buffs,
    defender_buffs,
    starfall_layers,
    options,
):
    return {
        value: _simulate_damage(
            our_panel,
            opponent_pet,
            level,
            skill,
            opponent_is_defender,
            stat_key,
            value,
            weather,
            attacker_buffs,
            defender_buffs,
            starfall_layers,
            options,
        )
        for value in values
    }


def _attack_defense_keys(skill):
    if skill.get("damage_class") == "物攻":
        return "atk", "def"
    if skill.get("damage_class") == "魔攻":
        return "spa", "spd"
    raise TeamAnalysisError(
        f"技能“{skill.get('name', '')}”没有物攻/魔攻类型，无法计算伤害。"
    )


def _record_buffs(record, key, fallback):
    if key not in record:
        return fallback
    try:
        return rc.normalize_buffs(record[key])
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(f"记录里的 {key}：{exc}") from exc


def _record_context(record, state, state_options, attacker, defender):
    """整理一条伤害记录当时的环境。"""
    weather = record["weather"] if "weather" in record else state.get("weather")
    attacker_buffs = _record_buffs(
        record, "attacker_buffs", attacker["buffs"]
    )
    defender_buffs = _record_buffs(
        record, "defender_buffs", defender["buffs"]
    )
    starfall = (
        _int_field(
            record.get("starfall_layers"),
            "记录里的星陨层数",
            0,
            rc.STARFALL_LAYER_LIMIT,
        )
        if "starfall_layers" in record
        else defender["starfall_layers"]
    )
    try:
        options = ra._damage_options(record, state_options)
    except (TypeError, ValueError) as exc:
        raise TeamAnalysisError(f"记录里的伤害选项不合法：{exc}") from exc
    return {
        "weather": weather,
        "attacker_buffs": attacker_buffs,
        "defender_buffs": defender_buffs,
        "starfall_layers": starfall,
        "options": options,
    }


# ---------------------------------------------------------------------------
# 记录过滤
# ---------------------------------------------------------------------------


def _filter_opponent_after_damage(
    opponent, damage_bits, damage_map, varying_key, hp_percent, rounding, level
):
    """扣掉伤害，并在填写了剩余百分比时进一步筛选候选取值。"""
    pet = opponent["pet"]
    stat_values = _stat_values(
        pet["number"], pet["form"], level, varying_key
    )
    max_hp_values = _stat_values(pet["number"], pet["form"], level, "hp")

    new_low = array("I", opponent["hp_lo"])
    new_high = array("I", opponent["hp_hi"])
    keep = bytearray((opponent["model"].total + 7) // 8)
    for index in _iter_bits(damage_bits):
        damage = damage_map[stat_values[index]]
        low = max(0, opponent["hp_lo"][index] - damage)
        high = max(0, opponent["hp_hi"][index] - damage)
        if hp_percent is not None:
            interval = _hp_interval(max_hp_values[index], hp_percent, rounding)
            if interval is None:
                continue
            low = max(low, interval[0])
            high = min(high, interval[1])
        if low <= high:
            keep[index >> 3] |= 1 << (index & 7)
            new_low[index] = low
            new_high[index] = high

    keep_bits = int.from_bytes(keep, "little")
    if keep_bits == 0:
        return None

    opponent["bits"] = keep_bits
    opponent["hp_lo"] = new_low
    opponent["hp_hi"] = new_high
    opponent["hp_touched"] = True
    return keep_bits


def _filter_opponent_hp_reset(opponent, percent, delta, rounding, level):
    """重置对方生命；填了实际变化量时，再用变化量筛选候选。"""
    pet = opponent["pet"]
    max_hp_values = _stat_values(pet["number"], pet["form"], level, "hp")
    new_low = array("I", opponent["hp_lo"])
    new_high = array("I", opponent["hp_hi"])
    keep = bytearray((opponent["model"].total + 7) // 8)

    for index in _iter_bits(opponent["bits"]):
        max_hp = max_hp_values[index]
        interval = _hp_interval(max_hp, percent, rounding)
        if interval is None:
            continue
        if delta is None:
            low, high = interval
        else:
            low = max(0, opponent["hp_lo"][index] + delta, interval[0])
            high = min(max_hp, opponent["hp_hi"][index] + delta, interval[1])
        if low <= high:
            keep[index >> 3] |= 1 << (index & 7)
            new_low[index] = low
            new_high[index] = high

    keep_bits = int.from_bytes(keep, "little")
    if keep_bits == 0:
        return None

    opponent["bits"] = keep_bits
    opponent["hp_lo"] = new_low
    opponent["hp_hi"] = new_high
    opponent["hp_touched"] = True
    return keep_bits


def _update_our_hp(our, damages, remaining_hp):
    """用伤害范围更新我方生命；如果填了具体剩余生命，就以它为准。"""
    damage_min = min(damages)
    damage_max = max(damages)
    expected_low = max(0, our["hp_lo"] - damage_max)
    expected_high = max(0, our["hp_hi"] - damage_min)
    warning = None
    if remaining_hp is not None:
        if not expected_low <= remaining_hp <= expected_high:
            warning = (
                f"按之前的生命和这次伤害，我方剩余生命应在 "
                f"{expected_low}～{expected_high} 之间，"
                f"但记录填的是 {remaining_hp}；已按你填的数字更新。"
            )
        our["hp_lo"] = remaining_hp
        our["hp_hi"] = remaining_hp
    else:
        our["hp_lo"] = expected_low
        our["hp_hi"] = expected_high
    return warning


def _apply_damage_record(record, state, state_options, our_slots, opp_slots):
    attacker_side = _normalize_side(record.get("attacker_side"), "攻击方")
    defender_side = _normalize_side(record.get("defender_side"), "防守方")
    if attacker_side == defender_side:
        raise TeamAnalysisError("攻击方和防守方不能是同一阵营。")

    attacker_slot = _slot_index(record.get("attacker_slot"), "攻击方位置")
    defender_slot = _slot_index(record.get("defender_slot"), "防守方位置")

    if defender_side == "theirs":
        if our_slots[attacker_slot] is None:
            raise TeamAnalysisError(
                f"我方第 {attacker_slot + 1} 个位置还没有选择精灵。"
            )
        if opp_slots[defender_slot] is None:
            raise TeamAnalysisError(
                f"对方第 {defender_slot + 1} 个位置还没有选择精灵。"
            )
        our = our_slots[attacker_slot]
        opponent = opp_slots[defender_slot]
        opponent_is_defender = True
        attacker = our
        defender = opponent
    else:
        if opp_slots[attacker_slot] is None:
            raise TeamAnalysisError(
                f"对方第 {attacker_slot + 1} 个位置还没有选择精灵。"
            )
        if our_slots[defender_slot] is None:
            raise TeamAnalysisError(
                f"我方第 {defender_slot + 1} 个位置还没有选择精灵。"
            )
        our = our_slots[defender_slot]
        opponent = opp_slots[attacker_slot]
        opponent_is_defender = False
        attacker = opponent
        defender = our

    skill_name = record.get("skill")
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise TeamAnalysisError("伤害记录必须说明用的是哪个技能。")
    try:
        skill = rc.find_skill(skill_name.strip())
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(str(exc)) from exc
    attack_key, defense_key = _attack_defense_keys(skill)

    recorded = record.get("damage")
    if (
        isinstance(recorded, bool)
        or not isinstance(recorded, (int, float))
        or not math.isfinite(recorded)
        or recorded < 0
        or not float(recorded).is_integer()
    ):
        raise TeamAnalysisError("伤害记录必须是非负整数。")
    recorded = int(recorded)

    context = _record_context(
        record, state, state_options, attacker, defender
    )
    varying_key = defense_key if opponent_is_defender else attack_key
    model = opponent["model"]
    values = model.possible_values(opponent["bits"], varying_key)
    if not values:
        return {
            "type": "damage",
            "matched": False,
            "kept": 0,
            "opponent_slot": opponent["slot"],
            "message": "这只对方精灵已经没有可能的组合，无法继续推断。",
        }, []

    damage_by_value = _damage_map(
        our["panel"],
        opponent["pet"],
        state["level"],
        skill,
        opponent_is_defender,
        varying_key,
        values,
        context["weather"],
        context["attacker_buffs"],
        context["defender_buffs"],
        context["starfall_layers"],
        context["options"],
    )
    matched_values = [
        value for value in values if damage_by_value[value] == recorded
    ]
    if not matched_values:
        return {
            "type": "damage",
            "matched": False,
            "kept": opponent["bits"].bit_count(),
            "opponent_slot": opponent["slot"],
            "message": (
                "伤害和当前范围对不上，请检查伤害、天气、增减益、"
                "星陨层数或连击。"
            ),
        }, []

    union = 0
    for value in matched_values:
        union |= model.value_bits[varying_key].get(value, 0)
    damage_bits = opponent["bits"] & union

    hp_percent = None
    remaining_hp = None
    if opponent_is_defender:
        if "remaining_hp" in record:
            raise TeamAnalysisError(
                "对方生命是隐藏的，请填剩余生命百分比 hp_percent，"
                "不要填 remaining_hp。"
            )
        hp_percent = _int_field(
            record.get("hp_percent"),
            "对方剩余生命百分比",
            0,
            100,
            required=False,
        )
    else:
        if "hp_percent" in record:
            raise TeamAnalysisError(
                "我方生命可以直接看到具体数字，请填 remaining_hp，"
                "不要填 hp_percent。"
            )
        remaining_hp = _int_field(
            record.get("remaining_hp"),
            "我方剩余生命",
            0,
            our["max_hp"],
            required=False,
        )

    warnings = []
    if opponent_is_defender:
        rounding = ra._select_rounding(
            record.get("rounding", state.get("hp_percent_rounding"))
        )
        new_bits = _filter_opponent_after_damage(
            opponent,
            damage_bits,
            damage_by_value,
            varying_key,
            hp_percent,
            rounding,
            state["level"],
        )
        if new_bits is None:
            return {
                "type": "damage",
                "matched": False,
                "kept": opponent["bits"].bit_count(),
                "opponent_slot": opponent["slot"],
                "message": (
                    "伤害对上了，但剩余生命百分比和当前范围对不上；"
                    "已跳过这条记录。"
                ),
            }, warnings
        message = (
            "同时用剩余生命百分比缩小了范围。"
            if hp_percent is not None
            else None
        )
    else:
        opponent["bits"] = damage_bits
        matched_damages = [damage_by_value[value] for value in matched_values]
        warning = _update_our_hp(our, matched_damages, remaining_hp)
        if warning:
            warnings.append(warning)
        if skill["name"] not in {
            entry["name"] for entry in opponent["skills"]
        } and skill["name"] not in opponent["observed_skills"]:
            opponent["observed_skills"].append(skill["name"])
        message = None

    return {
        "type": "damage",
        "matched": True,
        "kept": opponent["bits"].bit_count(),
        "opponent_slot": opponent["slot"],
        "message": message,
    }, warnings


def _apply_hp_change_record(record, our_slots, opp_slots, state):
    side = _normalize_side(record.get("side"), "记录阵营")
    slot = _slot_index(record.get("slot"), "记录位置")

    if side == "theirs":
        opponent = opp_slots[slot]
        if opponent is None:
            raise TeamAnalysisError(
                f"对方第 {slot + 1} 个位置还没有选择精灵。"
            )
        if "hp" in record:
            raise TeamAnalysisError(
                "对方生命是隐藏的，请填 hp_percent，不要填 hp。"
            )
        percent = _int_field(
            record.get("hp_percent"), "对方剩余生命百分比", 0, 100
        )
        delta = _int_field(
            record.get("hp_delta"),
            "对方生命实际变化量",
            required=False,
        )
        rounding = ra._select_rounding(
            record.get("rounding", state.get("hp_percent_rounding"))
        )
        new_bits = _filter_opponent_hp_reset(
            opponent, percent, delta, rounding, state["level"]
        )
        if new_bits is None:
            return {
                "type": "hp_change",
                "matched": False,
                "kept": opponent["bits"].bit_count(),
                "opponent_slot": slot,
                "message": (
                    "这个剩余百分比和实际变化量对不上；已跳过这条记录。"
                ),
            }, []
        message = (
            "只重置了生命百分比，没有使用实际变化量。"
            if delta is None
            else "已用实际变化量缩小当前生命范围。"
        )
        return {
            "type": "hp_change",
            "matched": True,
            "kept": opponent["bits"].bit_count(),
            "opponent_slot": slot,
            "message": message,
        }, []

    our = our_slots[slot]
    if our is None:
        raise TeamAnalysisError(f"我方第 {slot + 1} 个位置还没有选择精灵。")
    if "hp_percent" in record:
        raise TeamAnalysisError(
            "我方生命可以直接看到具体数字，请填 hp，不要填 hp_percent。"
        )
    hp = _int_field(record.get("hp"), "我方生命值", 0, our["max_hp"])
    our["hp_lo"] = hp
    our["hp_hi"] = hp
    return {
        "type": "hp_change",
        "matched": True,
        "kept": None,
        "opponent_slot": None,
        "message": f"我方生命已设为 {hp}。",
    }, []


# ---------------------------------------------------------------------------
# 技能伤害表
# ---------------------------------------------------------------------------


def _skill_entries_for_opponent(opponent):
    entries = list(opponent["skills"])
    names = {entry["name"] for entry in entries}
    for name in opponent["observed_skills"]:
        if name not in names:
            entries.append({"name": name, "observed": True})
            names.add(name)
    return entries


def _skill_options(state_options, entry):
    options = dict(state_options)
    if entry.get("power") is not None:
        options["power"] = entry["power"]
    if entry.get("hits") is not None:
        options["hit_count"] = entry["hits"]
    return options


def _skill_base(skill):
    return {
        "skill": skill["name"],
        "element": skill["element"],
        "damage_class": skill["damage_class"],
        "power": skill.get("power"),
    }


def _opponent_skill_groups(opponent, level):
    """把候选按「最大生命、防御、当前生命上下界」合并。

    技能伤害只取决于物防或魔防；剩余生命百分比还取决于最大生命和当前
    生命。同一组里这些值完全相同，因此每组只算一次即可，不需要让
    46,320 个候选分别乘以技能数量。
    """
    pet = opponent["pet"]
    hp_values = _stat_values(pet["number"], pet["form"], level, "hp")
    def_values = _stat_values(pet["number"], pet["form"], level, "def")
    spd_values = _stat_values(pet["number"], pet["form"], level, "spd")
    hp_low = opponent["hp_lo"]
    hp_high = opponent["hp_hi"]
    groups = {"def": {}, "spd": {}}

    for index in _iter_bits(opponent["bits"]):
        max_hp = hp_values[index]
        low = hp_low[index]
        high = hp_high[index]
        key = (max_hp, def_values[index], low, high)
        bucket = groups["def"]
        bucket[key] = bucket.get(key, 0) + 1
        key = (max_hp, spd_values[index], low, high)
        bucket = groups["spd"]
        bucket[key] = bucket.get(key, 0) + 1

    return groups


def _our_skill_range(our, opponent, entry, state, state_options, groups):
    try:
        skill = rc.find_skill(entry["name"])
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(str(exc)) from exc
    if skill.get("category") != "攻击" or skill.get("damage_class") not in (
        "物攻",
        "魔攻",
    ):
        result = _skill_base(skill)
        result.update({
            "available": False,
            "reason": "这个技能不造成直接伤害。",
        })
        return result

    if opponent["bits"] == 0:
        result = _skill_base(skill)
        result.update({
            "available": False,
            "reason": "这只对方精灵已经没有可能的组合。",
        })
        return result

    _, defense_key = _attack_defense_keys(skill)
    model = opponent["model"]
    values = model.possible_values(opponent["bits"], defense_key)
    options = _skill_options(state_options, entry)
    damage_by_value = _damage_map(
        our["panel"],
        opponent["pet"],
        state["level"],
        skill,
        True,
        defense_key,
        values,
        state.get("weather"),
        our["buffs"],
        opponent["buffs"],
        opponent["starfall_layers"],
        options,
    )

    damage_min = min(damage_by_value.values())
    damage_max = max(damage_by_value.values())
    remaining_min = math.inf
    remaining_max = -math.inf
    damage_percent_min = math.inf
    damage_percent_max = -math.inf
    certain = 0
    impossible = 0
    total = 0

    for (max_hp, defense, hp_low, hp_high), count in groups[
        defense_key
    ].items():
        damage = damage_by_value[defense]
        remaining_low = max(0, hp_low - damage)
        remaining_high = max(0, hp_high - damage)
        remaining_min = min(remaining_min, remaining_low / max_hp * 100)
        remaining_max = max(remaining_max, remaining_high / max_hp * 100)
        damage_percent_min = min(
            damage_percent_min, damage / max_hp * 100
        )
        damage_percent_max = max(
            damage_percent_max, damage / max_hp * 100
        )
        if hp_high <= damage:
            certain += count
        elif hp_low > damage:
            impossible += count
        total += count

    if certain == total:
        knockout = "certain"
    elif impossible == total:
        knockout = "impossible"
    else:
        knockout = "possible"

    result = _skill_base(skill)
    result.update({
        "available": True,
        "damage": {"min": damage_min, "max": damage_max},
        "remaining_hp_percent": {
            "min": round(remaining_min, 1),
            "max": round(remaining_max, 1),
        },
        "damage_percent": {
            "min": round(damage_percent_min, 1),
            "max": round(damage_percent_max, 1),
        },
        "knockout": knockout,
    })
    return result


def _opponent_skill_range(our, opponent, entry, state, state_options):
    try:
        skill = rc.find_skill(entry["name"])
    except rc.RocoCalcError as exc:
        raise TeamAnalysisError(str(exc)) from exc
    if skill.get("category") != "攻击" or skill.get("damage_class") not in (
        "物攻",
        "魔攻",
    ):
        result = _skill_base(skill)
        result.update({
            "available": False,
            "reason": "这个技能不造成直接伤害。",
        })
        return result

    if opponent["bits"] == 0:
        result = _skill_base(skill)
        result.update({
            "available": False,
            "reason": "这只对方精灵已经没有可能的组合。",
        })
        return result

    attack_key, _ = _attack_defense_keys(skill)
    model = opponent["model"]
    values = model.possible_values(opponent["bits"], attack_key)
    options = _skill_options(state_options, entry)
    damage_by_value = _damage_map(
        our["panel"],
        opponent["pet"],
        state["level"],
        skill,
        False,
        attack_key,
        values,
        state.get("weather"),
        opponent["buffs"],
        our["buffs"],
        our["starfall_layers"],
        options,
    )

    damage_min = min(damage_by_value.values())
    damage_max = max(damage_by_value.values())
    remaining_low = min(
        max(0, our["hp_lo"] - damage)
        for damage in damage_by_value.values()
    )
    remaining_high = max(
        max(0, our["hp_hi"] - damage)
        for damage in damage_by_value.values()
    )
    if our["hp_hi"] - damage_min <= 0:
        knockout = "certain"
    elif our["hp_lo"] - damage_max > 0:
        knockout = "impossible"
    else:
        knockout = "possible"

    result = _skill_base(skill)
    result.update({
        "available": True,
        "damage": {"min": damage_min, "max": damage_max},
        "our_remaining_hp": {"min": remaining_low, "max": remaining_high},
        "knockout": knockout,
    })
    return result


def _active_result(state, state_options, our_slots, opp_slots):
    our_slot = _slot_index(state.get("active_our_slot", 0), "当前我方位置")
    opp_slot = _slot_index(
        state.get("active_opponent_slot", 0), "当前对方位置"
    )
    our = our_slots[our_slot]
    opponent = opp_slots[opp_slot]
    if our is None or opponent is None:
        return None

    groups = _opponent_skill_groups(opponent, state["level"])
    return {
        "our_slot": our_slot,
        "opponent_slot": opp_slot,
        "our_skills": [
            _our_skill_range(
                our, opponent, entry, state, state_options, groups
            )
            for entry in our["skills"]
        ],
        "opponent_skills": [
            _opponent_skill_range(our, opponent, entry, state, state_options)
            for entry in _skill_entries_for_opponent(opponent)
        ],
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------


def _our_summary(our):
    panel = our["panel"]
    return {
        "slot": our["slot"],
        "configured": True,
        "side": "our",
        "pet": panel["pet"]["name"],
        "form": panel["pet"]["form"],
        "types": panel["pet"]["types"],
        "level": panel["level"],
        "nature": panel["nature"]["name"] if panel["nature"] else None,
        "talents": panel["talents"],
        "stats": panel["stats"],
        "buffs": our["buffs"],
        "max_hp": our["max_hp"],
        "current_hp": {"min": our["hp_lo"], "max": our["hp_hi"]},
        "speed_after_buffs": (
            panel["stats"]["spe"]
            + our["buffs"]["spe"] * rc.SPEED_POINTS_PER_LAYER
        ),
        "skills": [entry["name"] for entry in our["skills"]],
        "starfall_layers": our["starfall_layers"],
    }


def _opponent_summary(opponent, rounding):
    summary = ra._summarize(opponent["model"], opponent["bits"])
    summary.update({
        "slot": opponent["slot"],
        "configured": True,
        "side": "theirs",
        "pet": opponent["pet"]["name"],
        "form": opponent["pet"]["form"],
        "types": opponent["pet"]["types"],
        "buffs": opponent["buffs"],
        "starfall_layers": opponent["starfall_layers"],
        "configured_skills": [entry["name"] for entry in opponent["skills"]],
        "observed_skills": list(opponent["observed_skills"]),
    })

    if opponent["bits"] == 0:
        summary["current_hp"] = None
        summary["current_hp_percent"] = None
        return summary

    if not opponent.get("hp_touched"):
        summary["current_hp"] = {
            "min": summary["stats"]["hp"]["min"],
            "max": summary["stats"]["hp"]["max"],
        }
        summary["current_hp_percent"] = {"min": 100, "max": 100}
        return summary

    pet = opponent["pet"]
    max_hp_values = _stat_values(
        pet["number"], pet["form"], opponent["model"].level, "hp"
    )
    hp_low = math.inf
    hp_high = -math.inf
    percent_low = math.inf
    percent_high = -math.inf
    percent_cache = {}

    def display_percent(value, max_hp):
        key = (max_hp, value)
        cached = percent_cache.get(key)
        if cached is None:
            cached = ra._rounded_percent(value, max_hp, rounding)
            percent_cache[key] = cached
        return cached

    for index in _iter_bits(opponent["bits"]):
        max_hp = max_hp_values[index]
        low = opponent["hp_lo"][index]
        high = opponent["hp_hi"][index]
        hp_low = min(hp_low, low)
        hp_high = max(hp_high, high)
        percent_low = min(percent_low, display_percent(low, max_hp))
        percent_high = max(percent_high, display_percent(high, max_hp))
    summary["current_hp"] = {"min": hp_low, "max": hp_high}
    summary["current_hp_percent"] = {
        "min": round(percent_low, 1),
        "max": round(percent_high, 1),
    }
    return summary


def _empty_summary(index, our):
    return {
        "slot": index,
        "configured": False,
        "side": "our" if our else "theirs",
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def analyze_team(state):
    """输入双方 6 只精灵和战斗记录，返回每只对方精灵的可能范围。

    顶层字段：
        level / weather / hp_percent_rounding
        our_team          固定 6 个位置，未选择的位置 configured=false
        opponent_team     固定 6 个位置
        active            当前对位双方的技能伤害表，任一位置为空时为 null
        records           每条记录的处理结果，顺序与输入一致
        warnings          没有对上或被跳过的记录说明
    """
    if not isinstance(state, dict):
        raise TeamAnalysisError("输入必须是一个字典（整场队伍状态）。")

    level = rc._normalize_level(state.get("level", DEFAULT_LEVEL))
    state_options = ra._damage_options(state.get("options") or {})
    state = dict(state)
    state["level"] = level
    state["hp_percent_rounding"] = ra._select_rounding(
        state.get("hp_percent_rounding")
    )

    our_slots = _build_team(state, "our_team", "我方队伍", level, True)
    opp_slots = _build_team(state, "opponent_team", "对方队伍", level, False)

    records = state.get("records", [])
    if records is None:
        records = []
    if not isinstance(records, list):
        raise TeamAnalysisError("records 必须是列表。")

    results = []
    warnings = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise TeamAnalysisError(f"第 {index + 1} 条记录必须是字典。")
        kind = record.get("type", "damage")
        try:
            if kind == "damage":
                result, record_warnings = _apply_damage_record(
                    record, state, state_options, our_slots, opp_slots
                )
            elif kind in ("hp_change", "hp"):
                result, record_warnings = _apply_hp_change_record(
                    record, our_slots, opp_slots, state
                )
            else:
                raise TeamAnalysisError(
                    f"未知的记录类型“{kind}”；"
                    "可用类型：damage、hp_change。"
                )
        except TeamAnalysisError as exc:
            raise TeamAnalysisError(
                f"第 {index + 1} 条记录：{exc}"
            ) from exc
        except rc.RocoCalcError as exc:
            raise TeamAnalysisError(
                f"第 {index + 1} 条记录：{exc}"
            ) from exc

        result["index"] = index
        results.append(result)
        if not result["matched"]:
            warnings.append(
                f"第 {index + 1} 条记录没有对上，已跳过。{result['message']}"
            )
        for warning in record_warnings:
            warnings.append(f"第 {index + 1} 条记录：{warning}")

    our_team = [
        _our_summary(slot) if slot else _empty_summary(index, True)
        for index, slot in enumerate(our_slots)
    ]
    opponent_team = [
        _opponent_summary(slot, state["hp_percent_rounding"])
        if slot
        else _empty_summary(index, False)
        for index, slot in enumerate(opp_slots)
    ]

    return {
        "level": level,
        "weather": state.get("weather"),
        "hp_percent_rounding": state["hp_percent_rounding"],
        "our_team": our_team,
        "opponent_team": opponent_team,
        "active": _active_result(state, state_options, our_slots, opp_slots),
        "records": results,
        "warnings": warnings,
    }
