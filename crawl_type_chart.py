#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）属性克制/抵抗关系表爬取脚本

数据来源: wiki.biligame.com/nrc 的 Lua 数据模块 Module:Pets/data/Types
（游戏实际数据，比第三方攻略更权威；第三方攻略除草系→光系一处遗漏外与之一致）

输出:
    data/type_relations.csv    单属性克制/抵抗二元组表
    data/type_multipliers.csv  完整倍率表（含双属性组合）

关系语义（均为二元组，注意克制与抵抗不一定反对称）:
    (attack, defend) = 克制 -> 用 attack 系技能攻击 defend 系精灵，伤害 x2
    (attack, defend) = 抵抗 -> 用 attack 系技能攻击 defend 系精灵，伤害 x0.5
    双属性叠加: 双克制 x3、双抵抗 x0.25（非简单乘算 x4，见 wiki 实际数据）
    未出现在表中的组合 -> 伤害 x1

用法:
    python crawl_type_chart.py            联网抓取并生成 CSV
    python crawl_type_chart.py --cache    使用本地缓存（离线重跑）
"""

import csv
import os
import sys

# 复用精灵爬虫中的 Lua 表解析器与 MediaWiki 抓取/缓存逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_pets import LuaParser, load_or_fetch  # noqa: E402

TYPES_PAGE = "Module:Pets/data/Types"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT_RELATIONS = os.path.join(OUT_DIR, "type_relations.csv")
OUT_MULTIPLIERS = os.path.join(OUT_DIR, "type_multipliers.csv")

# 18 种属性（顺序即输出排序顺序）
TYPE_ORDER = [
    "草系", "火系", "水系", "光系", "地系", "冰系", "龙系", "电系", "毒系",
    "虫系", "武系", "翼系", "萌系", "幽系", "恶系", "普通系", "幻系", "机械系",
]
TYPE_SET = set(TYPE_ORDER)

RELATION_FIELDS = ["attack", "defend", "relation"]
MULTIPLIER_FIELDS = ["defend", "attack", "multiplier"]


def parse_types(wikitext):
    """解析 Types 模块，返回 (单属性二元组, 完整倍率条目)。

    模块结构: { ["光系"]={weak={{multiplier=2,type="草系"},...},resist={...}},
                ["光系|地系"]={...}, ... }
    其中 weak 是「被克制」（受攻击 x2 或 x3），resist 是「被抵抗」（x0.5 或 x0.25）。
    """
    root = LuaParser(wikitext).parse()

    relations = []   # 单属性 (attack, defend, relation)
    multipliers = []  # 全部 (defend, attack, multiplier)

    for defend, data in root.items():
        if not isinstance(data, dict):
            continue
        for item in data.get("weak", []):
            if not isinstance(item, dict):
                continue
            attack, mult = item.get("type"), item.get("multiplier")
            if attack is None or mult is None:
                continue
            multipliers.append({"defend": defend, "attack": attack, "multiplier": mult})
            # 单属性之间才归入二元组表；multiplier 2 为克制
            if defend in TYPE_SET and attack in TYPE_SET and mult == 2:
                relations.append({"attack": attack, "defend": defend, "relation": "克制"})
        for item in data.get("resist", []):
            if not isinstance(item, dict):
                continue
            attack, mult = item.get("type"), item.get("multiplier")
            if attack is None or mult is None:
                continue
            multipliers.append({"defend": defend, "attack": attack, "multiplier": mult})
            if defend in TYPE_SET and attack in TYPE_SET and mult == 0.5:
                relations.append({"attack": attack, "defend": defend, "relation": "抵抗"})

    return relations, multipliers


def defend_sort_key(name):
    """防御方属性组合的排序键：单属性在前，双属性按组成属性顺序。"""
    parts = name.split("|")
    return (len(parts) - 1, tuple(TYPE_ORDER.index(p) for p in parts))


def main():
    use_cache = "--cache" in sys.argv

    print("抓取/读取 Types 模块...")
    wikitext = load_or_fetch(TYPES_PAGE, use_cache)

    print("解析克制/抵抗关系...")
    relations, multipliers = parse_types(wikitext)

    # 单属性二元组表
    relations.sort(key=lambda r: (
        TYPE_ORDER.index(r["attack"]),
        TYPE_ORDER.index(r["defend"]),
        r["relation"],
    ))
    with open(OUT_RELATIONS, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RELATION_FIELDS)
        writer.writeheader()
        writer.writerows(relations)

    # 完整倍率表（含双属性组合）
    multipliers.sort(key=lambda r: (
        defend_sort_key(r["defend"]),
        TYPE_ORDER.index(r["attack"]),
    ))
    with open(OUT_MULTIPLIERS, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MULTIPLIER_FIELDS)
        writer.writeheader()
        writer.writerows(multipliers)

    n_super = sum(1 for r in relations if r["relation"] == "克制")
    n_resist = sum(1 for r in relations if r["relation"] == "抵抗")
    print(f"完成：单属性克制 {n_super} 组、抵抗 {n_resist} 组（共 {len(relations)} 行）。")
    print(f"完整倍率表 {len(multipliers)} 行（含 {sum(1 for m in multipliers if '|' in m['defend'])} 个双属性组合）。")
    print(f"输出：{OUT_RELATIONS}")
    print(f"输出：{OUT_MULTIPLIERS}")


if __name__ == "__main__":
    main()
