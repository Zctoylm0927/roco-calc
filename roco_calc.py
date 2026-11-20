#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）伤害计算核心库

本文件目前实现「面板值」计算：
    种族值 + 天分 + 性格 + 等级  →  战斗中的实际六维

公式来源与取整口径见 docs/architecture.md。当前以 rocopvp.tzrain.wiki
的计算器为准（用户指定的参考实现），并已用公开文章中的实例校验。

后续会在此基础上加入技能、属性克制与伤害计算。
"""

from __future__ import annotations

import csv
import math
import sys
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# 六项能力的内部键，与 data/pets.csv 的列名一致
STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_NAMES = {
    "hp": "生命",
    "atk": "物攻",
    "def": "物防",
    "spa": "魔攻",
    "spd": "魔防",
    "spe": "速度",
}
NAME_TO_KEY = {name: key for key, name in STAT_NAMES.items()}

# 18 种属性。顺序与爬虫 crawl_type_chart.py 一致，用于把双属性组合
# 规范成 data/type_multipliers.csv 中的键名顺序。
TYPE_ORDER = (
    "草系", "火系", "水系", "光系", "地系", "冰系", "龙系", "电系", "毒系",
    "虫系", "武系", "翼系", "萌系", "幽系", "恶系", "普通系", "幻系", "机械系",
)
TYPE_SET = set(TYPE_ORDER)


class RocoCalcError(Exception):
    """本库所有可预期错误的基类。"""


class DataError(RocoCalcError):
    """数据文件缺失或内容不合法。"""


class PetNotFoundError(RocoCalcError):
    """找不到精灵或指定形态。"""


class AmbiguousPetError(RocoCalcError):
    """同名精灵有多个形态，需要额外指定形态。"""

    def __init__(self, name, forms):
        self.name = name
        self.forms = forms
        super().__init__(
            f"精灵“{name}”有多个形态，请指定形态：" + "、".join(forms)
        )


class NatureNotFoundError(RocoCalcError):
    """找不到性格。"""


class TalentError(RocoCalcError):
    """天分数值不合法。"""


def _read_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise DataError(
            f"缺少数据文件 {path}。请先运行对应的 crawl_*.py 脚本生成。"
        )
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=None)
def load_pets():
    """读取 data/pets.csv，返回精灵字典元组（按文件顺序）。"""
    rows = _read_csv("pets.csv")
    pets = []
    for row in rows:
        pet = {
            "number": row.get("number", ""),
            "name": row.get("name", ""),
            "types": [t for t in row.get("types", "").split("|") if t],
            "stage": int(row["stage"]) if row.get("stage", "").isdigit() else row.get("stage", ""),
            "form": row.get("form", ""),
            "evolution_chain": row.get("evolution_chain", ""),
        }
        for key in STAT_KEYS:
            pet[key] = int(row[key])
        pets.append(pet)
    return tuple(pets)


@lru_cache(maxsize=None)
def load_natures():
    """读取 data/natures.csv，返回 {性格名: 性格字典}。"""
    rows = _read_csv("natures.csv")
    natures = {}
    for row in rows:
        natures[row["name"]] = {
            "nature_id": int(row["nature_id"]),
            "name": row["name"],
            "up_key": row["up_key"],
            "up_name": row["up_name"],
            "down_key": row["down_key"],
            "down_name": row["down_name"],
        }
    return natures


def _split_name_form(text, form=None):
    """支持「岚鸟(本来的样子)」或「岚鸟（本来的样子）」写法。"""
    name = str(text).strip()
    if form is not None:
        return name, str(form).strip()
    for left, right in (("(", ")"), ("（", "）")):
        if name.endswith(right) and left in name:
            idx = name.rfind(left)
            return name[:idx].strip(), name[idx + 1:-1].strip()
    return name, None


def find_pet(name, form=None):
    """按名称（或编号）查找精灵；同名多形态时必须指定 form。

    - 名称或编号完全匹配。
    - 若同名有多个形态，但其中只有一个基础形态（form 为空），默认取基础形态。
    - 否则抛出 AmbiguousPetError，并在错误信息里列出可选形态。
    """
    name, form = _split_name_form(name, form)
    matches = [p for p in load_pets() if p["name"] == name or p["number"] == name]
    if not matches:
        raise PetNotFoundError(f"找不到精灵“{name}”。")

    if form is not None:
        matches = [p for p in matches if p["form"] == form]
        if not matches:
            forms = sorted({p["form"] or "（基础形态）" for p in
                            (x for x in load_pets() if x["name"] == name or x["number"] == name)})
            raise PetNotFoundError(
                f"精灵“{name}”没有形态“{form}”。可选形态：" + "、".join(forms)
            )

    if len(matches) > 1:
        base_forms = [p for p in matches if not p["form"]]
        if len(base_forms) == 1:
            matches = base_forms
        else:
            forms = [p["form"] or "（基础形态）" for p in matches]
            raise AmbiguousPetError(name, forms)

    return matches[0]


def get_nature(nature):
    """把性格名解析成性格字典；None/“无”表示不加不减。"""
    if nature is None:
        return None
    if isinstance(nature, dict):
        return nature
    text = str(nature).strip()
    if text in ("", "无", "无性格", "不加不减"):
        return None
    natures = load_natures()
    if text not in natures:
        raise NatureNotFoundError(
            f"找不到性格“{text}”。可选性格：" + "、".join(natures.keys())
        )
    return natures[text]


def normalize_talents(talents=None):
    """把天分字典规范成六项齐全的 {键: 0–10} 字典。

    支持键名（hp/atk/...）或中文名（生命/物攻/...）。
    游戏规则：至多三项有加成，所以非零项不能超过 3 个。
    """
    result = {key: 0 for key in STAT_KEYS}
    if talents is None:
        return result
    if not isinstance(talents, dict):
        raise TalentError("天分必须是字典，例如 {'atk': 10, 'spe': 10}。")

    for raw_key, raw_value in talents.items():
        key = raw_key if raw_key in STAT_KEYS else NAME_TO_KEY.get(raw_key)
        if key is None:
            raise TalentError(f"未知能力名“{raw_key}”。可用：生命/物攻/物防/魔攻/魔防/速度。")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise TalentError(f"{STAT_NAMES[key]}的天分必须是 0–10 的整数。")
        if not 0 <= raw_value <= 10:
            raise TalentError(f"{STAT_NAMES[key]}的天分必须在 0–10 之间。")
        result[key] = raw_value

    if sum(1 for value in result.values() if value > 0) > 3:
        raise TalentError("天分最多只能给三项能力加成。")
    return result


def js_round(value):
    """模拟 JavaScript 的 Math.round（.5 向正无穷方向取整）。"""
    return math.floor(value + 0.5)


def _talent_round(value, talent):
    """tzrain 公式里的内层取整。

    当天分为 0 且数值恰好是 .5 时，使用「半到奇数」；其余情况用普通四舍五入。
    这个细节只在极端边界上差 1 点，但为了和参考计算器完全一致，照原样实现。
    """
    floor = math.floor(value)
    if talent == 0 and abs(value - floor - 0.5) < sys.float_info.epsilon * max(100.0, abs(value)):
        return floor + 1 if floor % 2 == 0 else floor
    return js_round(value)


def _normalize_level(level):
    """等级取整：非法或非有限值按 60 级处理；最低 1 级。"""
    try:
        value = float(level)
    except (TypeError, ValueError):
        return 60
    if not math.isfinite(value):
        return 60
    return max(1, js_round(value))


def calculate_stat(base, talent=0, nature=None, stat="hp", level=60):
    """计算单项面板值。

    base   种族值
    talent 该项天分（0–10）
    nature 性格名、性格字典或 None
    stat   能力键：hp/atk/def/spa/spd/spe
    level  等级，默认 60（PVP 标准）
    """
    if stat not in STAT_KEYS:
        raise RocoCalcError(f"未知能力键“{stat}”。")
    if isinstance(talent, bool) or not isinstance(talent, int):
        raise TalentError("天分必须是 0–10 的整数。")
    if not 0 <= talent <= 10:
        raise TalentError("天分必须在 0–10 之间。")

    level = _normalize_level(level)
    nature_obj = get_nature(nature)
    multiplier = 1.0
    if nature_obj:
        if nature_obj["up_key"] == stat:
            multiplier = 1.2
        elif nature_obj["down_key"] == stat:
            multiplier = 0.9

    if stat == "hp":
        inner = _talent_round((level / 50 + 0.5) * (base + 3 * talent), talent)
        return js_round((inner + level + 10) * multiplier) + 100

    inner = _talent_round((level / 100 + 0.5) * (base + 3 * talent), talent)
    return js_round((inner + 10) * multiplier) + 50


def calculate_panel(pet, nature=None, talents=None, level=60):
    """计算一只精灵的六项面板值，返回 {hp, atk, def, spa, spd, spe}。"""
    if isinstance(pet, str):
        pet = find_pet(pet)
    talents = normalize_talents(talents)
    nature_obj = get_nature(nature)
    level = _normalize_level(level)
    return {
        key: calculate_stat(pet[key], talents[key], nature_obj, key, level)
        for key in STAT_KEYS
    }


def build_panel(name, form=None, nature=None, talents=None, level=60):
    """查找精灵并计算面板，返回带上下文的完整结果。"""
    pet = find_pet(name, form)
    talents = normalize_talents(talents)
    nature_obj = get_nature(nature)
    level = _normalize_level(level)
    stats = {
        key: calculate_stat(pet[key], talents[key], nature_obj, key, level)
        for key in STAT_KEYS
    }
    return {
        "pet": pet,
        "nature": nature_obj,
        "talents": talents,
        "level": level,
        "stats": stats,
    }
