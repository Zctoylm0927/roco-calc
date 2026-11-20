#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）技能数据爬取脚本

数据来源: wiki.biligame.com/nrc 的 Lua 数据模块 Module:Pets/data/Skills

输出: data/skills.csv

字段说明:
    skill_id      模块内键名（如 skill_000688）
    game_id       游戏内技能 ID
    name          技能中文名
    category      技能类别：攻击 / 状态 / 防御 / 特性
    element       技能属性（状态/特性类可能为「无系别」）
    damage_class  伤害类型：物攻 / 魔攻（仅攻击技能有）
    power         基础威力（仅攻击技能有；部分特殊技能写 1，表示威力随规则变化）
    energy        能耗
    power_text    威力备注（如「变化」，仅极少数技能有）
    desc          技能描述

用法:
    python crawl_skills.py            联网抓取并生成 CSV
    python crawl_skills.py --cache    使用本地缓存（离线重跑）
"""

import csv
import os
import sys

# 复用精灵爬虫中的 Lua 表解析器与 MediaWiki 抓取/缓存逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_pets import LuaParser, load_or_fetch  # noqa: E402

SKILLS_PAGE = "Module:Pets/data/Skills"

OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "skills.csv")

FIELD_NAMES = [
    "skill_id", "game_id", "name", "category", "element",
    "damage_class", "power", "energy", "power_text", "desc",
]


def parse_skills(wikitext):
    """解析 Skills 模块，返回按 skill_id 排序的技能行列表。"""
    # 模块开头有一行 Lua 注释（-- 请勿直接修改本页面的数据。），
    # LuaParser 不处理注释，这里先去掉开头的注释行。
    lines = wikitext.splitlines()
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)

    root = LuaParser("\n".join(lines)).parse()
    rows = []
    for skill_id, raw in root.items():
        if not isinstance(raw, dict):
            continue
        rows.append({
            "skill_id": skill_id,
            "game_id": raw.get("game_id", ""),
            "name": raw.get("name", ""),
            "category": raw.get("category", ""),
            "element": raw.get("element", ""),
            "damage_class": raw.get("damage_class", ""),
            "power": raw.get("power", ""),
            "energy": raw.get("energy", ""),
            "power_text": raw.get("power_text", ""),
            "desc": raw.get("desc", ""),
        })

    def sort_key(row):
        suffix = row["skill_id"].rsplit("_", 1)[-1]
        return int(suffix) if suffix.isdigit() else 0

    rows.sort(key=sort_key)
    return rows


def main():
    use_cache = "--cache" in sys.argv

    print("抓取/读取 Skills 模块...")
    wikitext = load_or_fetch(SKILLS_PAGE, use_cache)

    print("解析技能数据...")
    rows = parse_skills(wikitext)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)

    n_attack = sum(1 for r in rows if r["category"] == "攻击")
    print(f"完成：共 {len(rows)} 个技能，其中攻击技能 {n_attack} 个。")
    print(f"输出文件：{OUT_CSV}")


if __name__ == "__main__":
    main()
