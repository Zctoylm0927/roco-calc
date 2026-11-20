#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对方未知性格/天分的范围推断。

我方精灵的性格、天分在战斗前已知；对方的只能看到一个精灵种类。本模块把
对方所有可能的「性格 + 六项天分」列成一个整体候选集合：

    30 种性格 × 1,544 种天分配置 = 46,320 种

其中天分配置要求「至少一项、至多三项非 0」，每项只能取 0/7/8/9/10；
性格恰好有一个提升项和一个降低项。过滤战斗记录时这两条全局约束会自动
生效，而不是六项属性各算各的。

实现上给每个候选一个编号（性格 × 天分），每项属性的每个取值预先算好一个
位图（Python 大整数）；一条记录就是几次位图求交，速度基本不随记录数增长。

入口：
    analyze_battle(state)  输入整场状态，返回对方范围和当前技能伤害范围
    build_candidates(pet)  列出完整候选（调试/测试用）

命令行演示见 analyze.py；前端接口设计见 docs/frontend-design.md。
"""

from __future__ import annotations

import itertools
import math
from functools import lru_cache

import roco_calc as rc

# 天分有加成的取值；0 表示没有加成。
TALENT_NONZERO_VALUES = (7, 8, 9, 10)
MIN_TALENT_BONUSES = 1
MAX_TALENT_BONUSES = 3

# 生命百分比的取整方式：四舍五入（默认）、向下、向上。
HP_PERCENT_ROUNDING_MODES = ("round", "floor", "ceil")

STAT_INDEX = {key: index for index, key in enumerate(rc.STAT_KEYS)}
TALENT_INDEX = {
    talent: index for index, talent in enumerate(rc.TALENT_VALUES)
}

# 伤害计算里可由调用方覆盖的选项，战斗记录和整场状态共用。
DAMAGE_OPTION_KEYS = (
    "power",
    "power_bonus",
    "power_percent",
    "damage_only_power_bonus",
    "damage_only_power_percent",
    "attack_modifier_percent",
    "defense_modifier_percent",
    "damage_reduction_percent",
    "damage_multiplier_percent",
    "hits",
    "misc_multiplier",
    "ignore_type_resistance",
)


class AnalysisError(rc.RocoCalcError):
    """范围推断的输入或记录不合法。"""


@lru_cache(maxsize=None)
def _talent_configs():
    """列出所有合法天分配置：至少 1 项、至多 3 项非 0。

    每项非 0 时取 7/8/9/10，共 24 + 240 + 1280 = 1,544 种。
    返回六元组，顺序与 roco_calc.STAT_KEYS 一致。
    """
    configs = []
    for count in range(MIN_TALENT_BONUSES, MAX_TALENT_BONUSES + 1):
        for keys in itertools.combinations(rc.STAT_KEYS, count):
            for values in itertools.product(TALENT_NONZERO_VALUES, repeat=count):
                talents = [0] * len(rc.STAT_KEYS)
                for key, value in zip(keys, values):
                    talents[STAT_INDEX[key]] = value
                configs.append(tuple(talents))
    return tuple(configs)


def _select_rounding(mode):
    if mode is None:
        return "round"
    text = str(mode).strip()
    if text not in HP_PERCENT_ROUNDING_MODES:
        raise AnalysisError(
            "生命百分比的取整方式只能是 round（四舍五入）、floor（向下）"
            "或 ceil（向上）。"
        )
    return text


def _rounded_percent(remaining_hp, max_hp, mode):
    """把「剩余生命 ÷ 最大生命」换算成界面显示的整数百分比。"""
    if remaining_hp <= 0:
        return 0
    value = remaining_hp / max_hp * 100
    if mode == "floor":
        return math.floor(value)
    if mode == "ceil":
        return math.ceil(value)
    return rc.js_round(value)


class _CandidateModel:
    """某个精灵在某个等级下的整体候选表。

    - 候选编号 = 性格序号 × 天分配置数 + 天分序号
    - value_bits[key][值] 是一个位图，第 i 位为 1 表示候选 i 的该项等于该值
    """

    def __init__(self, pet, level):
        self.pet = pet
        self.level = level
        self.natures = tuple(rc.load_natures().values())
        self.talents = _talent_configs()
        self.nature_count = len(self.natures)
        self.talent_count = len(self.talents)
        self.total = self.nature_count * self.talent_count
        self.mask = (1 << self.total) - 1

        self.values = {}
        self.value_bits = {}
        self._build_value_bits()

        per_nature = (1 << self.talent_count) - 1
        self.nature_bits = {
            nature["name"]: per_nature << (index * self.talent_count)
            for index, nature in enumerate(self.natures)
        }

    def _build_value_bits(self):
        byte_length = (self.total + 7) // 8
        for key in rc.STAT_KEYS:
            # 先算 30 种性格 × 5 档天分 = 150 个数值，再按候选展开。
            table = {}
            for nature in self.natures:
                table[nature["name"]] = tuple(
                    rc.calculate_stat(
                        self.pet[key], talent, nature, key, self.level
                    )
                    for talent in rc.TALENT_VALUES
                )

            stat_position = STAT_INDEX[key]
            buckets = {}
            index = 0
            for nature in self.natures:
                row = table[nature["name"]]
                for talents in self.talents:
                    value = row[TALENT_INDEX[talents[stat_position]]]
                    bucket = buckets.get(value)
                    if bucket is None:
                        bucket = buckets[value] = bytearray(byte_length)
                    bucket[index >> 3] |= 1 << (index & 7)
                    index += 1

            self.value_bits[key] = {
                value: int.from_bytes(bucket, "little")
                for value, bucket in buckets.items()
            }
            self.values[key] = sorted(self.value_bits[key])

    def possible_values(self, bits, key):
        return [
            value
            for value in self.values[key]
            if bits & self.value_bits[key][value]
        ]


@lru_cache(maxsize=None)
def _model_by_key(number, form, level):
    return _CandidateModel(rc.find_pet(number, form), level)


def _model_for(pet, level=60):
    """取得（并缓存）某个精灵的整体候选表。"""
    if isinstance(pet, str):
        pet = rc.find_pet(pet)
    if not isinstance(pet, dict):
        raise AnalysisError("精灵必须是名称或精灵字典。")
    level = rc._normalize_level(level)
    return _model_by_key(pet["number"], pet["form"], level)


def build_candidates(pet, level=60):
    """列出全部 46,320 个候选：{nature, talents}。

    talents 是长度 6 的元组，顺序与 roco_calc.STAT_KEYS 一致
    （生命、物攻、物防、魔攻、魔防、速度）。这个函数主要给调试和测试用，
    过滤记录时不需要真的展开列表。
    """
    model = _model_for(pet, level)
    return [
        {"nature": nature["name"], "talents": talents}
        for nature in model.natures
        for talents in model.talents
    ]


def initial_bits(pet, level=60):
    """全部候选都在时的位图（所有位都是 1）。"""
    return _model_for(pet, level).mask


def _check_bits(model, bits):
    if isinstance(bits, bool) or not isinstance(bits, int):
        raise AnalysisError("候选位图必须是整数。")
    if bits < 0 or bits & ~model.mask:
        raise AnalysisError("候选位图的位数超出了候选总数。")


def _filter_by_values(model, bits, key, allowed_values):
    if key not in rc.STAT_KEYS:
        raise AnalysisError(f"未知能力键“{key}”。")
    union = 0
    for value in allowed_values:
        union |= model.value_bits[key].get(value, 0)
    return bits & union


def apply_stat_values(bits, pet, stat_key, allowed_values, level=60):
    """只保留该项属性取值在 allowed_values 内的候选。"""
    model = _model_for(pet, level)
    _check_bits(model, bits)
    return _filter_by_values(model, bits, stat_key, allowed_values)


def _summarize(model, bits):
    stats = {}
    for key in rc.STAT_KEYS:
        values = model.possible_values(bits, key)
        stats[key] = {
            "min": values[0],
            "max": values[-1],
            "possible_values": values,
        }
    natures = [
        name
        for name, nature_bits in model.nature_bits.items()
        if bits & nature_bits
    ]
    return {
        "stats": stats,
        "builds": {"remaining": bits.bit_count(), "total": model.total},
        "natures_remaining": len(natures),
        "possible_natures": natures,
    }


def summarize(bits, pet, level=60):
    """把候选位图整理成前端需要的范围、组合数和可能性格。"""
    model = _model_for(pet, level)
    _check_bits(model, bits)
    return _summarize(model, bits)


def _damage_options(source, fallback=None):
    """从字典里取伤害选项，缺省时沿用 fallback（整场状态）。"""
    merged = {}
    if isinstance(fallback, dict):
        merged.update(fallback)
    if isinstance(source, dict):
        merged.update(source)
    return {
        "power": merged.get("power"),
        "power_bonus": float(merged.get("power_bonus", 0) or 0),
        "power_percent": float(merged.get("power_percent", 0) or 0),
        "damage_only_power_bonus": float(
            merged.get("damage_only_power_bonus", 0) or 0
        ),
        "damage_only_power_percent": float(
            merged.get("damage_only_power_percent", 0) or 0
        ),
        "attack_modifier_percent": float(
            merged.get("attack_modifier_percent", 0) or 0
        ),
        "defense_modifier_percent": float(
            merged.get("defense_modifier_percent", 0) or 0
        ),
        "damage_reduction_percent": float(
            merged.get("damage_reduction_percent", 0) or 0
        ),
        "damage_multiplier_percent": float(
            merged.get("damage_multiplier_percent", 100)
        ),
        # 整场状态里叫 hits，内部选项里叫 hit_count；两种都认。
        "hit_count": merged.get("hits", merged.get("hit_count", 1)),
        "misc_multiplier": float(merged.get("misc_multiplier", 1) or 1),
        "ignore_type_resistance": bool(
            merged.get("ignore_type_resistance", False)
        ),
    }


def _simulate_total_damage(
    context, skill, defense_key, defense_value
):
    """把守方该项防御设成 defense_value，模拟一次攻击的总伤害。

    其他守方数值与伤害无关（生命只影响百分比和击倒判断），这里统一填 1。
    """
    stats = {key: 1 for key in rc.STAT_KEYS}
    stats[defense_key] = defense_value
    defender = {
        "pet": context["opponent_pet"],
        "level": context["level"],
        "stats": stats,
    }
    result = rc.calculate_damage(
        context["our_panel"],
        defender,
        skill,
        weather=context["weather"],
        attacker_buffs=context["our_buffs"],
        defender_buffs=context["their_buffs"],
        starfall_layers=context["starfall_layers"],
        **context["options"],
    )
    return result["total_damage"]


def _observation_attacker(observation):
    attacker = str(observation.get("attacker", "our")).strip()
    if attacker in ("our", "我方", "我们"):
        return "our"
    if attacker in ("theirs", "对方", "敌方"):
        raise AnalysisError(
            "第一版只能记录“我方打对方”的伤害；对方打我方以后再支持。"
        )
    raise AnalysisError(
        "记录里的 attacker 只能是 our（我方）或 theirs（对方）。"
    )


def _apply_damage_observation(bits, observation, context):
    if _observation_attacker(observation) != "our":
        raise AnalysisError("第一版只能记录我方的攻击。")

    skill_name = observation.get("skill") or context["skill_name"]
    if not skill_name:
        raise AnalysisError("伤害记录必须说明用的是哪个技能。")
    skill = rc.find_skill(skill_name)
    if skill.get("damage_class") == "物攻":
        defense_key = "def"
    elif skill.get("damage_class") == "魔攻":
        defense_key = "spd"
    else:
        raise AnalysisError(
            f"技能“{skill.get('name', '')}”没有物攻/魔攻类型，无法计算伤害。"
        )

    recorded = observation.get("damage")
    if (
        isinstance(recorded, bool)
        or not isinstance(recorded, (int, float))
        or not math.isfinite(recorded)
        or recorded < 0
    ):
        raise AnalysisError("伤害记录必须是非负数字。")
    if not float(recorded).is_integer():
        raise AnalysisError("伤害记录必须是整数。")
    recorded = int(recorded)

    obs_context = dict(context)
    if "weather" in observation:
        obs_context["weather"] = observation["weather"]
    if "our_buffs" in observation:
        obs_context["our_buffs"] = rc.normalize_buffs(observation["our_buffs"])
    if "their_buffs" in observation:
        obs_context["their_buffs"] = rc.normalize_buffs(
            observation["their_buffs"]
        )
    if "starfall_layers" in observation:
        obs_context["starfall_layers"] = observation["starfall_layers"]
    obs_context["options"] = _damage_options(observation, context["options"])

    model = context["model"]
    values = model.possible_values(bits, defense_key)
    matched_values = [
        value
        for value in values
        if _simulate_total_damage(obs_context, skill, defense_key, value)
        == recorded
    ]

    if not matched_values:
        return bits, {
            "type": "damage",
            "matched": False,
            "kept": bits.bit_count(),
            "message": (
                "这条记录和当前规则对不上，请检查伤害、天气、增减益或星陨层数。"
            ),
        }

    new_bits = _filter_by_values(model, bits, defense_key, matched_values)
    return new_bits, {
        "type": "damage",
        "matched": True,
        "kept": new_bits.bit_count(),
        "message": None,
    }


def _apply_hp_percent_observation(bits, observation, context):
    percent = observation.get("hp_percent")
    if (
        isinstance(percent, bool)
        or not isinstance(percent, int)
        or not 0 <= percent <= 100
    ):
        raise AnalysisError("生命百分比必须是 0～100 的整数。")

    total_damage = observation.get("total_damage")
    if (
        isinstance(total_damage, bool)
        or not isinstance(total_damage, (int, float))
        or not math.isfinite(total_damage)
        or total_damage < 0
    ):
        raise AnalysisError("累计伤害必须是非负数字。")

    mode = _select_rounding(
        observation.get("rounding", context.get("hp_percent_rounding"))
    )
    model = context["model"]
    values = model.possible_values(bits, "hp")
    matched_values = [
        value
        for value in values
        if _rounded_percent(value - total_damage, value, mode) == percent
    ]

    if not matched_values:
        return bits, {
            "type": "hp_percent",
            "matched": False,
            "kept": bits.bit_count(),
            "message": (
                "生命百分比和当前范围对不上：请检查累计伤害，"
                "或对方是否回血、有护盾、取整方式不同。"
            ),
        }

    new_bits = _filter_by_values(model, bits, "hp", matched_values)
    return new_bits, {
        "type": "hp_percent",
        "matched": True,
        "kept": new_bits.bit_count(),
        "message": None,
    }


def apply_observation(bits, observation, context):
    """用一条战斗记录过滤候选。

    context 由 analyze_battle 准备，至少包含 model、our_panel、
    opponent_pet、level、skill_name、weather、our_buffs、their_buffs、
    starfall_layers、options、hp_percent_rounding。

    返回 (新的位图, 记录处理结果)。记录对不上时位图原样返回。
    """
    if not isinstance(observation, dict):
        raise AnalysisError("战斗记录必须是字典。")
    kind = observation.get("type", "damage")
    if kind == "damage":
        return _apply_damage_observation(bits, observation, context)
    if kind in ("hp_percent", "hp"):  # hp 是给旧请求留的简写
        return _apply_hp_percent_observation(bits, observation, context)
    raise AnalysisError(
        f"未知的记录类型“{kind}”；可用类型：damage、hp_percent。"
    )


def _pet_input(state, key, label):
    value = state.get(key)
    if not isinstance(value, dict):
        raise AnalysisError(f"{label}必须是字典，例如 {{\"name\": \"水灵\"}}。")
    if not value.get("name"):
        raise AnalysisError(f"{label}必须填写名称。")
    return value


def _damage_range(
    model,
    bits,
    our_panel,
    skill,
    our_buffs,
    their_buffs,
    weather,
    starfall_layers,
    options,
    level,
    opponent_pet,
):
    if skill.get("damage_class") == "物攻":
        defense_key = "def"
    elif skill.get("damage_class") == "魔攻":
        defense_key = "spd"
    else:
        raise rc.NotDamageSkillError(
            f"技能“{skill.get('name', '')}”没有物攻/魔攻类型，无法计算伤害。"
        )

    defense_values = model.possible_values(bits, defense_key)
    low_defense, high_defense = defense_values[0], defense_values[-1]
    context = {
        "our_panel": our_panel,
        "opponent_pet": opponent_pet,
        "level": level,
        "weather": weather,
        "our_buffs": our_buffs,
        "their_buffs": their_buffs,
        "starfall_layers": starfall_layers,
        "options": options,
    }
    damage_at_low_defense = _simulate_total_damage(
        context, skill, defense_key, low_defense
    )
    damage_at_high_defense = _simulate_total_damage(
        context, skill, defense_key, high_defense
    )
    damage_min = min(damage_at_low_defense, damage_at_high_defense)
    damage_max = max(damage_at_low_defense, damage_at_high_defense)

    hp_values = model.possible_values(bits, "hp")
    min_hp, max_hp = hp_values[0], hp_values[-1]
    if damage_min >= max_hp:
        knockout = "certain"
    elif damage_max < min_hp:
        knockout = "impossible"
    else:
        knockout = "possible"

    return {
        "skill": skill["name"],
        "defense_key": defense_key,
        "min": damage_min,
        "max": damage_max,
        "min_case_defense": high_defense,
        "max_case_defense": low_defense,
        "damage_percent_min": round(damage_min / max_hp * 100, 1),
        "damage_percent_max": round(damage_max / min_hp * 100, 1),
        "knockout": knockout,
    }


def analyze_battle(state):
    """输入整场状态，返回对方属性范围和当前技能伤害范围。

    state 的字段与 docs/frontend-design.md 第 5.2 节一致。
    """
    if not isinstance(state, dict):
        raise AnalysisError("输入必须是一个字典（整场状态）。")

    our = _pet_input(state, "our_pet", "我方精灵")
    opponent = _pet_input(state, "opponent_pet", "对方精灵")
    level = rc._normalize_level(state.get("level", 60))

    skill_name = state.get("skill")
    if not skill_name:
        raise AnalysisError("必须填写技能名称。")
    skill = rc.find_skill(skill_name)

    our_panel = rc.build_panel(
        our["name"],
        form=our.get("form"),
        nature=our.get("nature"),
        talents=our.get("talents"),
        level=level,
    )
    our_buffs = rc.normalize_buffs(our.get("buffs"))
    their_buffs = rc.normalize_buffs(opponent.get("buffs"))

    starfall_layers = state.get("starfall_layers", 0)
    weather = state.get("weather")
    rounding = _select_rounding(state.get("hp_percent_rounding"))

    opponent_pet = rc.find_pet(opponent["name"], opponent.get("form"))
    model = _model_for(opponent_pet, level)
    bits = model.mask

    context = {
        "model": model,
        "our_panel": our_panel,
        "opponent_pet": opponent_pet,
        "level": level,
        "skill_name": skill_name,
        "weather": weather,
        "our_buffs": our_buffs,
        "their_buffs": their_buffs,
        "starfall_layers": starfall_layers,
        "options": _damage_options(state),
        "hp_percent_rounding": rounding,
    }

    observations = state.get("observations", [])
    if observations is None:
        observations = []
    if not isinstance(observations, list):
        raise AnalysisError("observations 必须是列表。")

    results = []
    warnings = []
    for index, observation in enumerate(observations):
        try:
            bits, result = apply_observation(bits, observation, context)
        except rc.RocoCalcError as exc:
            raise AnalysisError(f"第 {index + 1} 条记录：{exc}") from exc
        result["index"] = index
        results.append(result)
        if not result["matched"]:
            warnings.append(
                f"第 {index + 1} 条记录没有对上，已跳过。{result['message']}"
            )

    opponent_result = _summarize(model, bits)
    opponent_result["pet"] = opponent_pet["name"]
    opponent_result["form"] = opponent_pet["form"]
    opponent_result["level"] = level
    opponent_result["observations"] = results
    opponent_result["warnings"] = warnings

    return {
        "opponent": opponent_result,
        "damage": _damage_range(
            model,
            bits,
            our_panel,
            skill,
            our_buffs,
            their_buffs,
            weather,
            starfall_layers,
            context["options"],
            level,
            opponent_pet,
        ),
    }
