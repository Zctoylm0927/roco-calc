#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整对局日志的校验、重放和范围推断。

对局文件是原始事实：初始双方 6 只精灵、每一回合双方行动、伤害/生命变化、
回合结束快照。性格和天分范围是从这些事实里推导出来的，不直接写进原始日志。
"""

from __future__ import annotations

import roco_analysis as ra
import roco_calc as rc
import roco_skill_rules as rsr
import roco_team as rt

BATTLE_VERSION = 1
DEFAULT_MAGIC_POINTS = 4
DEFAULT_MAX_ENERGY = 10
SPEED_LAYER_POINTS = rc.SPEED_POINTS_PER_LAYER

POSITIVE_MARKS = {
    "攻击印记",
    "光合印记",
    "湿润印记",
    "蓄电印记",
    "风起印记",
    "蓄势印记",
    "龙噬印记",
    "萌芽印记",
}
NEGATIVE_MARKS = {
    "中毒印记",
    "棘刺印记",
    "降灵印记",
    "减速印记",
    "星陨印记",
    "暗涌印记",
}
PERMANENT_STATUSES = {"冻结", "萌化", "引电"}
TEMPORARY_STATUSES = {"中毒", "灼烧", "寄生", "禁足"}
IGNORED_STATUSES = {"木桶状态", "月陨星状态"}

SUPPORTED_WEATHER = {None, "", "雨天"}

# 第一版不建模的特殊攻击技能；出现时该伤害事件只记录，不参与推断。
SPECIAL_ATTACK_SKILLS = {
    "魔能爆",
    "怨力打击",
    "钢钻",
    "冰锋横扫",
    "砂糖弹球",
}


class BattleLogError(ra.AnalysisError):
    """对局日志不合法。"""


_MISSING = object()


def _int_field(value, label, minimum=None, maximum=None, *, default=_MISSING):
    if value is None:
        if default is not _MISSING:
            return default
        raise BattleLogError(f"{label}必须填写。")
    if isinstance(value, bool) or not isinstance(value, int):
        raise BattleLogError(f"{label}必须是整数。")
    if minimum is not None and value < minimum:
        raise BattleLogError(f"{label}不能小于 {minimum}。")
    if maximum is not None and value > maximum:
        raise BattleLogError(f"{label}不能大于 {maximum}。")
    return value


def _bool_field(value, label, default=False):
    if value is None:
        return default
    if not isinstance(value, bool):
        raise BattleLogError(f"{label}必须是 true 或 false。")
    return value


def _slot(value, label, *, default=None):
    if value is None:
        if default is not None:
            return default
        raise BattleLogError(f"{label}必须填写。")
    return rt._slot_index(value, label)


def _side(value, label, *, default=None):
    if value is None:
        if default is not None:
            return default
        raise BattleLogError(f"{label}必须填写。")
    return rt._normalize_side(value, label)


def _team_raw(state, key, label):
    return rt._team_list(state, key, label)


def _parse_weather(raw, label):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典或空值。")
    kind = raw.get("type")
    if kind in (None, ""):
        return None
    if not isinstance(kind, str):
        raise BattleLogError(f"{label}的天气名称必须是文本。")
    remaining = _int_field(
        raw.get("remaining"), f"{label}的剩余回合", 0, default=0
    )
    return {"type": kind, "remaining": remaining}


def _parse_marks(raw, label):
    if raw is None:
        return {"positive": None, "negative": None}
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典或空值。")
    result = {}
    for kind, names in (("positive", POSITIVE_MARKS), ("negative", NEGATIVE_MARKS)):
        item = raw.get(kind)
        if item is None:
            result[kind] = None
            continue
        if not isinstance(item, dict):
            raise BattleLogError(f"{label}的{kind}必须是字典或空值。")
        name = item.get("name")
        if name not in names:
            raise BattleLogError(
                f"{label}的{kind}“{name}”不是已知的"
                f"{'正面' if kind == 'positive' else '负面'}印记。"
            )
        layers = _int_field(
            item.get("layers"), f"{label}的{name}层数", 0, default=0
        )
        result[kind] = {"name": name, "layers": layers} if layers else None
    return result


def _parse_statuses(raw, label):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BattleLogError(f"{label}必须是列表。")
    result = []
    seen = set()
    for position, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise BattleLogError(f"{label}第 {position} 项必须是字典。")
        name = item.get("name")
        if name in IGNORED_STATUSES:
            continue
        if name not in PERMANENT_STATUSES and name not in TEMPORARY_STATUSES:
            raise BattleLogError(f"{label}第 {position} 项的状态“{name}”未知。")
        if name in seen:
            raise BattleLogError(f"{label}里的状态“{name}”重复了。")
        seen.add(name)
        layers = _int_field(
            item.get("layers"), f"{label}的{name}层数", 0, default=0
        )
        permanent = name in PERMANENT_STATUSES
        if item.get("permanent") is not None and item["permanent"] != permanent:
            raise BattleLogError(
                f"{label}的{name}永久性不对；{name}是"
                f"{'永久' if permanent else '非永久'}状态。"
            )
        if layers:
            result.append({"name": name, "layers": layers, "permanent": permanent})
    return result


def _parse_buffs(raw, label):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    temporary = raw.get("temporary", raw.get("temporary_buffs"))
    permanent = raw.get("permanent", raw.get("permanent_buffs"))
    if temporary is None and "buffs_temporary" in raw:
        temporary = raw.get("buffs_temporary")
    if permanent is None and "buffs_permanent" in raw:
        permanent = raw.get("buffs_permanent")
    try:
        return {
            "temporary": rc.normalize_buffs(temporary),
            "permanent": rc.normalize_buffs(permanent),
        }
    except rc.RocoCalcError as exc:
        raise BattleLogError(f"{label}：{exc}") from exc


def _merge_buffs(buffs):
    temporary = buffs.get("temporary") or {}
    permanent = buffs.get("permanent") or {}
    result = {}
    for key in rc.BUFF_KEYS:
        value = int(temporary.get(key, 0)) + int(permanent.get(key, 0))
        result[key] = max(-rc.BUFF_LAYER_LIMIT, min(rc.BUFF_LAYER_LIMIT, value))
    return result


def _parse_magic_points(raw, label):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    return {
        "our": _int_field(
            raw.get("our"),
            f"{label}的我方魔力值",
            0,
            DEFAULT_MAGIC_POINTS,
            default=DEFAULT_MAGIC_POINTS,
        ),
        "opp": _int_field(
            raw.get("opp"),
            f"{label}的对方魔力值",
            0,
            DEFAULT_MAGIC_POINTS,
            default=DEFAULT_MAGIC_POINTS,
        ),
    }


def _initial_pet_entry(raw, side, index):
    label = f"{'我方' if side == 'our' else '对方'}第 {index + 1} 只精灵"
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    max_energy = _int_field(
        raw.get("max_energy"),
        f"{label}的能量上限",
        1,
        999,
        default=DEFAULT_MAX_ENERGY,
    )
    energy = _int_field(
        raw.get("energy"),
        f"{label}的初始能量",
        0,
        max_energy,
        default=max_energy,
    )
    return {
        "hp": None if side == "opp" else 0,
        "hp_percent": 100 if side == "opp" else None,
        "energy": energy,
        "max_energy": max_energy,
        "buffs": {"temporary": rc.normalize_buffs(None), "permanent": rc.normalize_buffs(None)},
        "statuses": [],
    }


def _build_initial(raw):
    if not isinstance(raw, dict):
        raise BattleLogError("initial 必须是字典。")
    level = rc._normalize_level(raw.get("level", rt.DEFAULT_LEVEL))
    opponent_team = []
    for item in _team_raw(raw, "opponent_team", "对方队伍"):
        if isinstance(item, dict) and "skills" not in item and "suspected_skills" in item:
            item = dict(item)
            item["skills"] = item.get("suspected_skills")
        opponent_team.append(item)
    state = {
        "level": level,
        "our_team": _team_raw(raw, "our_team", "我方队伍"),
        "opponent_team": opponent_team,
        "hp_percent_rounding": ra._select_rounding(
            raw.get("hp_percent_rounding")
        ),
    }
    our_slots = rt._build_team(state, "our_team", "我方队伍", level, True)
    opp_slots = rt._build_team(
        state, "opponent_team", "对方队伍", level, False
    )
    active_our = _slot(
        raw.get("active_our", raw.get("active_our_slot")),
        "我方首发位置",
        default=0,
    )
    active_opp = _slot(
        raw.get("active_opp", raw.get("active_opponent_slot")),
        "对方首发位置",
        default=0,
    )
    if our_slots[active_our] is None:
        raise BattleLogError("我方首发位置还没有选择精灵。")
    if opp_slots[active_opp] is None:
        raise BattleLogError("对方首发位置还没有选择精灵。")

    our_entries = []
    for index, slot in enumerate(our_slots):
        if slot is None:
            our_entries.append(None)
            continue
        raw_slot = state["our_team"][index]
        entry = _initial_pet_entry(raw_slot, "our", index)
        entry["hp"] = slot["max_hp"]
        entry["max_hp"] = slot["max_hp"]
        our_entries.append(entry)
    opp_entries = []
    for index, slot in enumerate(opp_slots):
        if slot is None:
            opp_entries.append(None)
            continue
        raw_slot = state["opponent_team"][index]
        opp_entries.append(_initial_pet_entry(raw_slot, "opp", index))

    snapshot = {
        "active_our": active_our,
        "active_opp": active_opp,
        "weather": None,
        "our_marks": {"positive": None, "negative": None},
        "opp_marks": {"positive": None, "negative": None},
        "magic_points": _parse_magic_points(raw.get("magic_points"), "初始魔力值"),
        "our_pets": our_entries,
        "opp_pets": opp_entries,
    }
    return {
        "level": level,
        "our_slots": our_slots,
        "opp_slots": opp_slots,
        "snapshot": snapshot,
        "hp_percent_rounding": state["hp_percent_rounding"],
    }


def _parse_pet_entry(raw, side, index, slot, label):
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    max_energy = _int_field(
        raw.get("max_energy"),
        f"{label}的能量上限",
        1,
        999,
        default=DEFAULT_MAX_ENERGY,
    )
    energy = _int_field(
        raw.get("energy"),
        f"{label}的能量",
        0,
        max_energy,
        default=max_energy,
    )
    buffs = _parse_buffs(raw.get("buffs"), f"{label}的增减益")
    statuses = _parse_statuses(raw.get("statuses"), f"{label}的状态")
    if side == "our":
        max_hp = slot["max_hp"]
        return {
            "hp": _int_field(raw.get("hp"), f"{label}的当前生命", 0, max_hp),
            "max_hp": max_hp,
            "energy": energy,
            "max_energy": max_energy,
            "buffs": buffs,
            "statuses": statuses,
        }
    return {
        "hp_percent": _int_field(
            raw.get("hp_percent"), f"{label}的当前生命百分比", 0, 100
        ),
        "energy": energy,
        "max_energy": max_energy,
        "buffs": buffs,
        "statuses": statuses,
    }


def _parse_pet_entries(raw, slots, side, label):
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise BattleLogError(f"{label}必须是列表。")
    if len(raw) > rt.MAX_TEAM_SIZE:
        raise BattleLogError(f"{label}最多 6 项。")
    result = []
    for index in range(rt.MAX_TEAM_SIZE):
        item = raw[index] if index < len(raw) else None
        slot = slots[index]
        if slot is None:
            result.append(None)
            continue
        if item is None:
            raise BattleLogError(f"{label}第 {index + 1} 项缺少。")
        result.append(
            _parse_pet_entry(
                item, side, index, slot,
                f"{label}第 {index + 1} 只精灵",
            )
        )
    return result


def _parse_snapshot(raw, our_slots, opp_slots, level, label):
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    active_our = _slot(
        raw.get("active_our", raw.get("active_our_slot")),
        f"{label}的我方当前出战位置",
        default=0,
    )
    active_opp = _slot(
        raw.get("active_opp", raw.get("active_opponent_slot")),
        f"{label}的对方当前出战位置",
        default=0,
    )
    if our_slots[active_our] is None:
        raise BattleLogError(f"{label}的我方出战位置还没有精灵。")
    if opp_slots[active_opp] is None:
        raise BattleLogError(f"{label}的对方出战位置还没有精灵。")
    return {
        "active_our": active_our,
        "active_opp": active_opp,
        "weather": _parse_weather(raw.get("weather"), f"{label}的天气"),
        "our_marks": _parse_marks(raw.get("our_marks"), f"{label}的我方印记"),
        "opp_marks": _parse_marks(raw.get("opp_marks"), f"{label}的对方印记"),
        "magic_points": _parse_magic_points(
            raw.get("magic_points"), f"{label}的魔力值"
        ),
        "our_pets": _parse_pet_entries(
            raw.get("our_pets"), our_slots, "our", f"{label}的我方精灵"
        ),
        "opp_pets": _parse_pet_entries(
            raw.get("opp_pets"), opp_slots, "opp", f"{label}的对方精灵"
        ),
    }


def _snapshot_active(snapshot, side):
    if side == "our":
        slot = snapshot["active_our"]
        return slot, snapshot["our_pets"][slot]
    slot = snapshot["active_opp"]
    return slot, snapshot["opp_pets"][slot]


def _parse_action(raw, side, slot, label):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典或空值。")
    kind = raw.get("type")
    if kind == "switch":
        action_slot = _slot(raw.get("slot"), f"{label}的行动位置", default=slot)
        if action_slot != slot:
            raise BattleLogError(f"{label}的行动位置应为当前出战位置 {slot + 1}。")
        target = _slot(raw.get("to_slot"), f"{label}的切换目标")
        if target == slot:
            raise BattleLogError(f"{label}不能切换到当前出战的精灵。")
        return {"type": "switch", "slot": slot, "to_slot": target}
    if kind == "charge":
        action_slot = _slot(raw.get("slot"), f"{label}的行动位置", default=slot)
        if action_slot != slot:
            raise BattleLogError(f"{label}的行动位置应为当前出战位置 {slot + 1}。")
        return {"type": "charge", "slot": slot}
    if kind == "skill":
        action_slot = _slot(raw.get("slot"), f"{label}的行动位置", default=slot)
        if action_slot != slot:
            raise BattleLogError(f"{label}的行动位置应为当前出战位置 {slot + 1}。")
        name = raw.get("skill")
        if not isinstance(name, str) or not name.strip():
            raise BattleLogError(f"{label}必须填写技能名。")
        name = name.strip()
        try:
            skill = rc.find_skill(name)
        except rc.RocoCalcError as exc:
            raise BattleLogError(f"{label}：{exc}") from exc
        if skill.get("category") not in rsr.ACTION_CATEGORIES:
            raise BattleLogError(
                f"{label}的技能“{name}”不是可行动技能（攻击/防御/状态）。"
            )
        return {
            "type": "skill",
            "slot": slot,
            "skill": name,
            "category": skill["category"],
            "description": skill.get("desc", ""),
            "skill_data": skill,
        }
    raise BattleLogError(
        f"{label}的类型只能是 skill、charge、switch 或空值。"
    )


def _action_skill(action):
    if action and action.get("type") == "skill":
        return action["skill_data"]
    return None


def _action_category(action):
    if not action:
        return None
    if action["type"] == "charge":
        return "状态"
    return action.get("category")


def _public_action(action):
    if not action:
        return None
    result = {"type": action["type"], "slot": action["slot"]}
    if action["type"] in ("skill", "switch"):
        if "skill" in action:
            result["skill"] = action["skill"]
        if "to_slot" in action:
            result["to_slot"] = action["to_slot"]
    return result


def _action_description(action):
    return action.get("description", "") if action else ""


def _priority_for(action, intended_skill, label):
    if action is None:
        if intended_skill is None:
            return None, None
        try:
            skill = rc.find_skill(intended_skill)
        except rc.RocoCalcError as exc:
            raise BattleLogError(f"{label}原本打算用的技能：{exc}") from exc
        value, note = rsr.skill_priority(skill.get("desc", ""))
        return value, (note, skill)
    if action["type"] == "switch":
        return 99, None
    if action["type"] == "charge":
        return 0, None
    value, note = rsr.skill_priority(action.get("description", ""))
    return value, (note, action["skill_data"])


def _counter_for(our_action, opp_action):
    return rsr.counter_happened(
        _action_category(our_action),
        _action_description(our_action),
        _action_category(opp_action),
        _action_description(opp_action),
    )


def _speed_buff_layers(entry):
    buffs = entry.get("buffs") or {}
    return int((buffs.get("temporary") or {}).get("spe", 0)) + int(
        (buffs.get("permanent") or {}).get("spe", 0)
    )


def _our_speed(slot, entry):
    return slot["panel"]["stats"]["spe"] + _speed_buff_layers(entry) * SPEED_LAYER_POINTS


def _apply_speed_constraint(opponent, speed_buff_layers, our_speed, first_side, level):
    speed_values = rt._stat_values(
        opponent["pet"]["number"], opponent["pet"]["form"], level, "spe"
    )
    keep = bytearray((opponent["model"].total + 7) // 8)
    kept = 0
    for index in rt._iter_bits(opponent["bits"]):
        opp_speed = speed_values[index] + speed_buff_layers * SPEED_LAYER_POINTS
        if first_side == "our":
            ok = opp_speed <= our_speed
        else:
            ok = opp_speed >= our_speed
        if ok:
            keep[index >> 3] |= 1 << (index & 7)
            kept += 1
    if kept == 0:
        return (
            f"速度关系对不上：按填写的先后顺序，对方第 {opponent['slot'] + 1} "
            "只精灵没有符合条件的性格/天分；已跳过这条速度约束。"
        )
    opponent["bits"] = int.from_bytes(keep, "little")
    return None


def _parse_context(raw, label):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典或空值。")
    weather = _parse_weather(raw.get("weather"), f"{label}的天气")
    our_marks = _parse_marks(raw.get("our_marks"), f"{label}的我方印记")
    opp_marks = _parse_marks(raw.get("opp_marks"), f"{label}的对方印记")
    our_active = raw.get("our_active")
    opp_active = raw.get("opp_active")
    if not isinstance(our_active, dict) or not isinstance(opp_active, dict):
        raise BattleLogError(f"{label}必须包含 our_active 和 opp_active。")
    return {
        "weather": weather,
        "our_marks": our_marks,
        "opp_marks": opp_marks,
        "our_active": our_active,
        "opp_active": opp_active,
    }


def _context_entry(raw, side, label):
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    return {
        "slot": _slot(raw.get("slot"), f"{label}的位置", default=0),
        "hp": _int_field(
            raw.get("hp"), f"{label}的生命", 0, default=None
        ) if side == "our" else None,
        "hp_percent": _int_field(
            raw.get("hp_percent"), f"{label}的生命百分比", 0, 100, default=None
        ) if side == "opp" else None,
        "energy": _int_field(
            raw.get("energy"), f"{label}的能量", 0, 999, default=None
        ),
        "max_energy": _int_field(
            raw.get("max_energy"), f"{label}的能量上限", 1, 999, default=DEFAULT_MAX_ENERGY
        ),
        "buffs": _parse_buffs(raw.get("buffs"), f"{label}的增减益"),
        "statuses": _parse_statuses(raw.get("statuses"), f"{label}的状态"),
    }


def _context_has_unmodeled_statuses(entry, label):
    if entry.get("statuses"):
        return f"{label}带有状态（{entry['statuses'][0]['name']}），第一版暂不推断。"
    return None


def _context_mark_layers(marks, name):
    for kind in ("positive", "negative"):
        item = marks.get(kind)
        if item and item["name"] == name:
            return item["layers"]
    return 0


def _context_has_unmodeled_marks(marks, label):
    for kind in ("positive", "negative"):
        item = marks.get(kind)
        if item and item["layers"] and item["name"] != "星陨印记":
            return f"{label}带有印记“{item['name']}”，第一版暂不推断。"
    return None


def _damage_event_record(event, context, defender_action, level, rounding):
    """把对局事件整理成 roco_team 能用的伤害记录。"""
    source = _side(event.get("source_side"), "伤害来源")
    target = _side(event.get("target_side"), "伤害目标")
    if source == target:
        raise BattleLogError("伤害来源和伤害目标不能是同一阵营。")
    source_slot = _slot(event.get("source_slot"), "伤害来源位置", default=0)
    target_slot = _slot(event.get("target_slot"), "伤害目标位置", default=0)
    our_active = _context_entry(context["our_active"], "our", "伤害事件的我方场上精灵")
    opp_active = _context_entry(context["opp_active"], "opp", "伤害事件的对方场上精灵")
    if source == "our" and our_active["slot"] != source_slot:
        return None, "伤害来源位置和发生时的我方场上精灵对不上。"
    if target == "our" and our_active["slot"] != target_slot:
        return None, "伤害目标位置和发生时的我方场上精灵对不上。"
    if source == "theirs" and opp_active["slot"] != source_slot:
        return None, "伤害来源位置和发生时的对方场上精灵对不上。"
    if target == "theirs" and opp_active["slot"] != target_slot:
        return None, "伤害目标位置和发生时的对方场上精灵对不上。"
    skill_name = event.get("skill")
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise BattleLogError("伤害事件必须填写技能名。")
    skill_name = skill_name.strip()
    try:
        skill = rc.find_skill(skill_name)
    except rc.RocoCalcError as exc:
        raise BattleLogError(f"伤害事件：{exc}") from exc
    if skill.get("category") != "攻击":
        return None, "这个技能不是攻击技能，第一版不用于伤害推断。"
    if skill.get("damage_class") not in ("物攻", "魔攻"):
        return None, "这个攻击技能没有物攻/魔攻类型，第一版不用于伤害推断。"
    if skill_name in SPECIAL_ATTACK_SKILLS:
        return None, f"技能“{skill_name}”的威力规则第一版未建模。"

    weather = context["weather"]
    if weather and weather["type"] not in SUPPORTED_WEATHER:
        return None, f"天气“{weather['type']}”第一版未建模。"
    for side, marks, label in (
        ("our", context["our_marks"], "我方"),
        ("theirs", context["opp_marks"], "对方"),
    ):
        issue = _context_has_unmodeled_marks(marks, f"{label}场上")
        if issue:
            return None, issue

    for side, entry, label in (
        ("our", our_active, "我方场上精灵"),
        ("theirs", opp_active, "对方场上精灵"),
    ):
        issue = _context_has_unmodeled_statuses(entry, label)
        if issue:
            return None, issue

    defender_is_defense = (
        defender_action
        and defender_action.get("type") == "skill"
        and defender_action.get("category") == "防御"
    )
    reduction = 0
    extra_defense_buffs = {}
    if defender_is_defense:
        plan = rsr.defense_damage_plan(
            defender_action["skill"], defender_action.get("description", "")
        )
        if not plan["supported"]:
            return None, plan["reason"]
        reduction = plan["reduction"] or 0
        extra_defense_buffs = rsr.defense_pre_damage_layers(
            defender_action["skill"], skill["damage_class"]
        )

    if source == "our":
        attacker = our_active
        defender = opp_active
    else:
        attacker = opp_active
        defender = our_active

    attacker_buffs = _merge_buffs(attacker["buffs"])
    defender_buffs = _merge_buffs(defender["buffs"])
    for key, layers in extra_defense_buffs.items():
        defender_buffs[key] = max(defender_buffs.get(key, 0), layers)

    starfall = _context_mark_layers(
        context["opp_marks"] if target == "theirs" else context["our_marks"],
        "星陨印记",
    )
    damage = event.get("total_damage")
    if damage is None:
        hit_damage = _int_field(event.get("hit_damage"), "每段伤害", 0)
        hits = _int_field(event.get("hits"), "连击数", 1, default=1)
        damage = hit_damage * hits
    else:
        damage = _int_field(damage, "总伤害", 0)
        hits = _int_field(event.get("hits"), "连击数", 1, default=1)

    record = {
        "type": "damage",
        "attacker_side": source,
        "attacker_slot": source_slot,
        "defender_side": target,
        "defender_slot": target_slot,
        "skill": skill_name,
        "damage": damage,
        "hits": hits,
        "weather": weather["type"] if weather else None,
        "attacker_buffs": attacker_buffs,
        "defender_buffs": defender_buffs,
        "starfall_layers": starfall,
        "damage_reduction_percent": reduction,
        "rounding": rounding,
    }
    hp_after = event.get("hp_after")
    if not isinstance(hp_after, dict):
        raise BattleLogError("伤害事件必须填写 hp_after。")
    if target == "theirs":
        record["hp_percent"] = _int_field(
            hp_after.get("hp_percent"), "伤害后的对方生命百分比", 0, 100,
            default=None,
        )
    else:
        record["remaining_hp"] = _int_field(
            hp_after.get("hp"), "伤害后的我方生命", 0, default=None
        )
    return record, None


def _hp_change_record(event):
    target = _side(event.get("target_side"), "生命变化目标")
    slot = _slot(event.get("target_slot"), "生命变化位置", default=0)
    hp_after = event.get("hp_after")
    if not isinstance(hp_after, dict):
        raise BattleLogError("生命变化事件必须填写 hp_after。")
    if target == "theirs":
        return {
            "type": "hp_change",
            "side": "theirs",
            "slot": slot,
            "hp_percent": _int_field(
                hp_after.get("hp_percent"),
                "生命变化后的对方生命百分比",
                0,
                100,
            ),
            "hp_delta": _int_field(
                event.get("amount"), "生命实际变化量", default=None
            ),
        }
    return {
        "type": "hp_change",
        "side": "our",
        "slot": slot,
        "hp": _int_field(
            hp_after.get("hp"), "生命变化后的我方生命", 0
        ),
    }


def _apply_snapshot_hp(snapshot, our_slots, opp_slots, level, rounding):
    warnings = []
    for index, opponent in enumerate(opp_slots):
        if opponent is None or opponent["bits"] == 0:
            continue
        entry = snapshot["opp_pets"][index]
        percent = entry["hp_percent"]
        if not rt._filter_opponent_hp_reset(
            opponent, percent, None, rounding, level
        ):
            warnings.append(
                f"第 {index + 1} 只对方精灵的回合结束生命百分比"
                f"（{percent}%）和推断范围对不上，已跳过这条生命约束。"
            )
    for index, our in enumerate(our_slots):
        if our is None:
            continue
        hp = snapshot["our_pets"][index]["hp"]
        our["hp_lo"] = hp
        our["hp_hi"] = hp
    return warnings


def _apply_final_buffs(snapshot, our_slots, opp_slots):
    for index, our in enumerate(our_slots):
        if our is None:
            continue
        entry = snapshot["our_pets"][index]
        our["buffs"] = _merge_buffs(entry["buffs"])
        our["buffs_temporary"] = entry["buffs"]["temporary"]
        our["buffs_permanent"] = entry["buffs"]["permanent"]
        our["statuses"] = entry["statuses"]
    starfall = _context_mark_layers(snapshot["opp_marks"], "星陨印记")
    for index, opponent in enumerate(opp_slots):
        if opponent is None:
            continue
        entry = snapshot["opp_pets"][index]
        opponent["buffs"] = _merge_buffs(entry["buffs"])
        opponent["buffs_temporary"] = entry["buffs"]["temporary"]
        opponent["buffs_permanent"] = entry["buffs"]["permanent"]
        opponent["statuses"] = entry["statuses"]
        opponent["starfall_layers"] = starfall


def _summarize_team(our_slots, opp_slots, snapshot, rounding):
    our_team = []
    for index, slot in enumerate(our_slots):
        if slot is None:
            our_team.append(rt._empty_summary(index, True))
            continue
        summary = rt._our_summary(slot)
        entry = snapshot["our_pets"][index]
        summary["energy"] = entry["energy"]
        summary["max_energy"] = entry["max_energy"]
        summary["buffs_temporary"] = entry["buffs"]["temporary"]
        summary["buffs_permanent"] = entry["buffs"]["permanent"]
        summary["statuses"] = entry["statuses"]
        our_team.append(summary)
    opponent_team = []
    for index, slot in enumerate(opp_slots):
        if slot is None:
            opponent_team.append(rt._empty_summary(index, False))
            continue
        summary = rt._opponent_summary(slot, rounding)
        entry = snapshot["opp_pets"][index]
        summary["energy"] = entry["energy"]
        summary["max_energy"] = entry["max_energy"]
        summary["buffs_temporary"] = entry["buffs"]["temporary"]
        summary["buffs_permanent"] = entry["buffs"]["permanent"]
        summary["statuses"] = entry["statuses"]
        opponent_team.append(summary)
    return our_team, opponent_team


def _validate_replacements(raw, our_slots, opp_slots, snapshot, label):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}的补位必须是字典。")
    result = {}
    for side, slots in (("our", our_slots), ("opp", opp_slots)):
        value = raw.get(side)
        if value is None:
            result[side] = None
            continue
        slot = _slot(value, f"{label}的{'我方' if side == 'our' else '对方'}补位")
        if slots[slot] is None:
            raise BattleLogError(f"{label}的补位位置没有精灵。")
        hp = (
            snapshot["our_pets"][slot]["hp"]
            if side == "our"
            else snapshot["opp_pets"][slot]["hp_percent"]
        )
        if hp == 0:
            raise BattleLogError(f"{label}的补位精灵已经没有生命。")
        result[side] = slot
    return result


def _turn_speed(
    turn, our_action, opp_action, our_intended, opp_intended,
    pre_snapshot, our_slots, opp_slots, level,
):
    counter = _counter_for(our_action, opp_action)
    counter = _bool_field(turn.get("counter"), "本回合是否发生应对", counter) or counter
    who_first = turn.get("who_first")
    if who_first not in (None, "our", "opp"):
        raise BattleLogError("who_first 只能是 our、opp 或空值。")
    if our_action is None and opp_action is None:
        raise BattleLogError("双方行动不能同时为空。")

    if counter:
        return False, None, "本回合发生了应对，不能用来推断速度。", counter

    our_priority, our_extra = _priority_for(
        our_action, our_intended, "我方行动"
    )
    opp_priority, opp_extra = _priority_for(
        opp_action, opp_intended, "对方行动"
    )
    if our_priority is None or opp_priority is None:
        return False, None, "有一方被击倒、没有记录原本打算用的技能，无法判断先手度。", counter
    if our_extra and our_extra[0]:
        return False, None, f"我方技能条件先手（{our_extra[0]}），暂不推断速度。", counter
    if opp_extra and opp_extra[0]:
        return False, None, f"对方技能条件先手（{opp_extra[0]}），暂不推断速度。", counter
    if our_priority != opp_priority:
        return False, None, "双方先手度不同，不能用来推断速度。", counter

    our_switch = bool(our_action and our_action["type"] == "switch")
    opp_switch = bool(opp_action and opp_action["type"] == "switch")
    if our_switch != opp_switch:
        return False, None, "只有一方切换，不能用来推断速度。", counter
    if who_first is None:
        return False, None, "没有填写谁先行动，不能推断速度。", counter

    if our_action is None:
        acting_side = "opp"
    elif opp_action is None:
        acting_side = "our"
    else:
        acting_side = who_first
    if (our_action is None or opp_action is None) and who_first != acting_side:
        return False, None, "谁先行动和空行动对不上，不能推断速度。", counter

    our_slot, our_entry = _snapshot_active(pre_snapshot, "our")
    opp_slot, opp_entry = _snapshot_active(pre_snapshot, "opp")
    our_speed = _our_speed(our_slots[our_slot], our_entry)
    opp_speed_layers = _speed_buff_layers(opp_entry)
    return {
        "first_side": "our" if who_first == "our" else "theirs",
        "our_speed": our_speed,
        "opp_slot": opp_slot,
        "opp_speed_layers": opp_speed_layers,
    }, (our_slot, opp_slot), None, counter


def _replay_turn(
    index, raw, level, our_slots, opp_slots, pre_snapshot, rounding,
    state_options, initial_magic, ko_counted,
):
    label = f"第 {index + 1} 回合"
    if not isinstance(raw, dict):
        raise BattleLogError(f"{label}必须是字典。")
    our_slot = pre_snapshot["active_our"]
    opp_slot = pre_snapshot["active_opp"]
    our_action = _parse_action(raw.get("our_action"), "our", our_slot, "我方行动")
    opp_action = _parse_action(raw.get("opp_action"), "theirs", opp_slot, "对方行动")
    if pre_snapshot["our_pets"][our_slot]["hp"] == 0 and our_action is not None:
        raise BattleLogError(f"{label}：我方当前精灵已经没有生命，行动必须为空。")
    if pre_snapshot["opp_pets"][opp_slot]["hp_percent"] == 0 and opp_action is not None:
        raise BattleLogError(f"{label}：对方当前精灵已经没有生命，行动必须为空。")
    our_intended = raw.get("our_intended_skill")
    opp_intended = raw.get("opp_intended_skill")
    if our_action is None and our_intended is not None:
        if not isinstance(our_intended, str) or not our_intended.strip():
            raise BattleLogError("我方未执行技能必须是技能名。")
        our_intended = our_intended.strip()
    else:
        our_intended = None
    if opp_action is None and opp_intended is not None:
        if not isinstance(opp_intended, str) or not opp_intended.strip():
            raise BattleLogError("对方未执行技能必须是技能名。")
        opp_intended = opp_intended.strip()
    else:
        opp_intended = None

    warnings = []
    event_results = []
    our_energy = pre_snapshot["our_pets"][our_slot]["energy"]
    opp_energy = pre_snapshot["opp_pets"][opp_slot]["energy"]
    if our_action and our_action["type"] == "skill":
        configured = {entry["name"] for entry in our_slots[our_slot]["skills"]}
        if our_action["skill"] not in configured:
            raise BattleLogError(
                f"{label}：我方技能“{our_action['skill']}”不在这个位置配置的技能里。"
            )
    if opp_action and opp_action["type"] == "skill":
        opponent = opp_slots[opp_slot]
        learnset = rc.load_action_learnsets().get(
            (opponent["pet"]["name"], opponent["pet"]["form"]), ()
        )
        if learnset and opp_action["skill"] not in learnset:
            warnings.append(
                f"对方技能“{opp_action['skill']}”不在已抓取的对方可学技能表里；"
                "仍按记录使用。"
            )
    for side, action, energy in (
        ("我方", our_action, our_energy),
        ("对方", opp_action, opp_energy),
    ):
        if action and action["type"] == "skill":
            cost = action["skill_data"].get("energy") or 0
            if cost > energy:
                warnings.append(
                    f"{side}使用“{action['skill']}”需要 {cost} 能量，"
                    f"但回合开始时只有 {energy}；第一版特殊能量技能未建模。"
                )
        if action and action["type"] == "switch":
            active_entry = (
                pre_snapshot["our_pets"][our_slot]
                if side == "我方"
                else pre_snapshot["opp_pets"][opp_slot]
            )
            if any(s["name"] == "禁足" for s in active_entry["statuses"]):
                raise BattleLogError(f"{label}：{side}当前处于禁足状态，不能切换。")
            target_entry = (
                pre_snapshot["our_pets"][action["to_slot"]]
                if side == "我方"
                else pre_snapshot["opp_pets"][action["to_slot"]]
            )
            if target_entry is None:
                raise BattleLogError(f"{label}：切换目标没有精灵。")
            if any(s["name"] == "禁足" for s in target_entry["statuses"]):
                raise BattleLogError(f"{label}：切换目标处于禁足状态。")
            target_hp = (
                target_entry["hp"]
                if side == "我方"
                else target_entry["hp_percent"]
            )
            if target_hp == 0:
                raise BattleLogError(f"{label}：切换目标已经没有生命。")

    speed_info, _speed_slots, speed_warning, counter = _turn_speed(
        raw, our_action, opp_action, our_intended, opp_intended,
        pre_snapshot, our_slots, opp_slots, level,
    )
    declared_speed = raw.get("speed_inferable")
    if declared_speed is not None and not isinstance(declared_speed, bool):
        raise BattleLogError("speed_inferable 必须是 true、false 或空值。")
    if declared_speed is False:
        speed_info = None
    elif declared_speed is True and not speed_info:
        warnings.append(
            "本回合记录标记为可以推断速度，但按行动和先手度判断无法使用；"
            f"已按不能推断处理。{speed_warning or ''}".strip()
        )
    if speed_warning and speed_info:
        warnings.append(speed_warning)
    if speed_info:
        opponent = opp_slots[speed_info["opp_slot"]]
        if opponent:
            warning = _apply_speed_constraint(
                opponent,
                speed_info["opp_speed_layers"],
                speed_info["our_speed"],
                speed_info["first_side"],
                level,
            )
            if warning:
                warnings.append(warning)

    events = raw.get("events", [])
    if events is None:
        events = []
    if not isinstance(events, list):
        raise BattleLogError(f"{label}的 events 必须是列表。")
    for event_index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise BattleLogError(f"{label}第 {event_index} 个事件必须是字典。")
        kind = event.get("type")
        event_label = f"{label}第 {event_index} 个事件"
        try:
            if kind == "damage":
                if event.get("ignore_for_inference"):
                    event_results.append({
                        "index": event_index - 1,
                        "type": "damage",
                        "matched": False,
                        "kept": None,
                        "message": "按事件标记跳过了推断。",
                    })
                    continue
                context = _parse_context(event.get("context"), f"{event_label}的状态")
                if context is None:
                    event_results.append({
                        "index": event_index - 1,
                        "type": "damage",
                        "matched": False,
                        "kept": None,
                        "message": "缺少伤害发生时的状态，第一版不用于推断。",
                    })
                    continue
                target_side = _side(event.get("target_side"), "伤害目标")
                defender_action = opp_action if target_side == "theirs" else our_action
                record, reason = _damage_event_record(
                    event, context, defender_action, level, rounding
                )
                if record is None:
                    event_results.append({
                        "index": event_index - 1,
                        "type": "damage",
                        "matched": False,
                        "kept": None,
                        "message": reason,
                    })
                    continue
                result, record_warnings = rt._apply_damage_record(
                    record, {"level": level, "weather": None,
                             "hp_percent_rounding": rounding,
                             "options": state_options},
                    state_options, our_slots, opp_slots,
                )
                result["index"] = event_index - 1
                event_results.append(result)
                warnings.extend(record_warnings)
                if not result["matched"]:
                    warnings.append(
                        f"{event_label}没有对上，已跳过。{result.get('message', '')}"
                    )
            elif kind in ("hp_change", "hp"):
                record = _hp_change_record(event)
                result, record_warnings = rt._apply_hp_change_record(
                    record, our_slots, opp_slots,
                    {"level": level, "weather": None,
                     "hp_percent_rounding": rounding},
                )
                result["index"] = event_index - 1
                event_results.append(result)
                warnings.extend(record_warnings)
                if not result["matched"]:
                    warnings.append(
                        f"{event_label}没有对上，已跳过。{result.get('message', '')}"
                    )
            else:
                raise BattleLogError(
                    f"{event_label}的类型只能是 damage 或 hp_change。"
                )
        except (rt.TeamAnalysisError, rc.RocoCalcError, BattleLogError) as exc:
            raise BattleLogError(f"{event_label}：{exc}") from exc

    if opp_action and opp_action["type"] == "skill":
        opponent = opp_slots[opp_slot]
        if opponent and opp_action["skill"] not in opponent["observed_skills"]:
            opponent["observed_skills"].append(opp_action["skill"])

    snapshot = _parse_snapshot(
        raw.get("snapshot_after"), our_slots, opp_slots, level,
        f"{label}结束快照",
    )
    replacements = _validate_replacements(
        raw.get("replacements"), our_slots, opp_slots, snapshot, label
    )
    expected_our = our_slot
    expected_opp = opp_slot
    if our_action and our_action["type"] == "switch":
        expected_our = our_action["to_slot"]
    if opp_action and opp_action["type"] == "switch":
        expected_opp = opp_action["to_slot"]
    if snapshot["our_pets"][expected_our]["hp"] == 0 and replacements["our"] is not None:
        expected_our = replacements["our"]
    if (
        snapshot["opp_pets"][expected_opp]["hp_percent"] == 0
        and replacements["opp"] is not None
    ):
        expected_opp = replacements["opp"]
    if snapshot["active_our"] != expected_our:
        raise BattleLogError(
            f"{label}结束时我方场上精灵和前面的行动/补位对不上。"
        )
    if snapshot["active_opp"] != expected_opp:
        raise BattleLogError(
            f"{label}结束时对方场上精灵和前面的行动/补位对不上。"
        )

    warnings.extend(
        _apply_snapshot_hp(snapshot, our_slots, opp_slots, level, rounding)
    )

    for side, entries in (
        ("our", snapshot["our_pets"]),
        ("opp", snapshot["opp_pets"]),
    ):
        for slot, entry in enumerate(entries):
            if entry is None:
                continue
            hp = entry["hp"] if side == "our" else entry["hp_percent"]
            if hp == 0 and slot not in ko_counted[side]:
                ko_counted[side].add(slot)
    expected_magic = {
        "our": max(0, initial_magic["our"] - len(ko_counted["our"])),
        "opp": max(0, initial_magic["opp"] - len(ko_counted["opp"])),
    }
    for side, label_text in (("our", "我方"), ("opp", "对方")):
        if snapshot["magic_points"][side] != expected_magic[side]:
            warnings.append(
                f"{label_text}魔力值和击倒次数对不上：按击倒数应为 "
                f"{expected_magic[side]}，记录填的是 "
                f"{snapshot['magic_points'][side]}；以记录为准。"
            )

    return {
        "turn": index + 1,
        "our_action": _public_action(our_action),
        "opp_action": _public_action(opp_action),
        "who_first": raw.get("who_first"),
        "counter": counter,
        "speed_inferable": bool(speed_info),
        "events": event_results,
        "replacements": replacements,
        "snapshot_after": snapshot,
        "warnings": warnings,
    }


def _winner_from_snapshot(snapshot, our_slots, opp_slots):
    magic = snapshot["magic_points"]
    our_alive = any(
        slot is not None and snapshot["our_pets"][index]["hp"] > 0
        for index, slot in enumerate(our_slots)
    )
    opp_alive = any(
        slot is not None and snapshot["opp_pets"][index]["hp_percent"] > 0
        for index, slot in enumerate(opp_slots)
    )
    if magic["our"] == 0 and magic["opp"] == 0:
        return {"winner": "draw", "reason": "magic"}
    if magic["our"] == 0:
        return {"winner": "opp", "reason": "magic"}
    if magic["opp"] == 0:
        return {"winner": "our", "reason": "magic"}
    if not our_alive:
        return {"winner": "opp", "reason": "no_bench"}
    if not opp_alive:
        return {"winner": "our", "reason": "no_bench"}
    return None


def analyze_battle_log(payload):
    """校验并分析一整场对局日志。"""
    if not isinstance(payload, dict):
        raise BattleLogError("对局日志必须是一个字典。")
    version = payload.get("version", BATTLE_VERSION)
    if version != BATTLE_VERSION:
        raise BattleLogError(f"暂不支持对局日志版本 {version}。")
    initial = _build_initial(payload.get("initial"))
    level = initial["level"]
    our_slots = initial["our_slots"]
    opp_slots = initial["opp_slots"]
    snapshot = initial["snapshot"]
    rounding = initial["hp_percent_rounding"]
    state_options = ra._damage_options(payload.get("options") or {})

    turns = payload.get("turns", [])
    if turns is None:
        turns = []
    if not isinstance(turns, list):
        raise BattleLogError("turns 必须是列表。")
    results = []
    warnings = []
    initial_magic = snapshot["magic_points"]
    ko_counted = {"our": set(), "opp": set()}
    for index, turn in enumerate(turns):
        result = _replay_turn(
            index, turn, level, our_slots, opp_slots, snapshot,
            rounding, state_options, initial_magic, ko_counted,
        )
        results.append(result)
        warnings.extend(result["warnings"])
        snapshot = result["snapshot_after"]

    _apply_final_buffs(snapshot, our_slots, opp_slots)
    our_team, opponent_team = _summarize_team(
        our_slots, opp_slots, snapshot, rounding
    )
    active_state = {
        "active_our_slot": snapshot["active_our"],
        "active_opponent_slot": snapshot["active_opp"],
    }
    active_weather = (
        snapshot["weather"]["type"] if snapshot["weather"] else None
    )
    active = rt._active_result(
        {**active_state, "level": level, "weather": active_weather},
        state_options, our_slots, opp_slots,
    )
    result = payload.get("result")
    if result is not None and not isinstance(result, dict):
        raise BattleLogError("result 必须是字典或空值。")
    computed_result = _winner_from_snapshot(snapshot, our_slots, opp_slots)
    if result is None:
        result = computed_result
    elif computed_result is not None:
        if result.get("winner") != computed_result["winner"]:
            warnings.append(
                "记录里的胜方和按生命/魔力值算出的胜方不一致；以记录为准。"
            )
    return {
        "version": BATTLE_VERSION,
        "level": level,
        "our_team": our_team,
        "opponent_team": opponent_team,
        "active": active,
        "turns": results,
        "snapshot": snapshot,
        "magic_points": snapshot["magic_points"],
        "result": result,
        "warnings": warnings,
    }
