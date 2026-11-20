#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）性格数据爬取脚本

数据来源: wiki.biligame.com/nrc 的 Lua 数据模块 Module:Natures/data

输出: data/natures.csv

字段说明:
    nature_id   性格编号（1–30）
    name        性格中文名
    up_key      提升的能力（内部键：hp/atk/def/spa/spd/spe）
    up_name     提升的能力（中文）
    down_key    降低的能力（内部键）
    down_name   降低的能力（中文）

用法:
    python crawl_natures.py            联网抓取并生成 CSV
    python crawl_natures.py --cache    使用本地缓存（离线重跑）
"""

import csv
import os
import sys

# 复用精灵爬虫中的 Lua 表解析器与 MediaWiki 抓取/缓存逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_pets import LuaParser, load_or_fetch  # noqa: E402

NATURES_PAGE = "Module:Natures/data"

OUT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "natures.csv")

FIELD_NAMES = ["nature_id", "name", "up_key", "up_name", "down_key", "down_name"]

# 中文能力名 → 内部键。内部键与 data/pets.csv 的六项种族值字段一致。
STAT_NAME_TO_KEY = {
    "生命": "hp",
    "物攻": "atk",
    "物防": "def",
    "魔攻": "spa",
    "魔防": "spd",
    "速度": "spe",
}


def parse_natures(wikitext):
    """解析 Natures/data 模块，返回按编号排序的性格行列表。

    模块结构:
        { stats = {{id=80,name="物攻"}, ...},
          rows  = {{down=82,id=1,name="大胆",up=80}, ...} }
    """
    root = LuaParser(wikitext).parse()
    stats = root.get("stats", [])
    rows = root.get("rows", [])

    id2stat = {}
    for stat in stats:
        if isinstance(stat, dict) and stat.get("id") is not None:
            name = stat.get("name", "")
            key = STAT_NAME_TO_KEY.get(name)
            if not key:
                raise ValueError(f"未知能力名：{name!r}")
            id2stat[stat["id"]] = (key, name)

    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        up_key, up_name = id2stat[row["up"]]
        down_key, down_name = id2stat[row["down"]]
        result.append({
            "nature_id": row["id"],
            "name": row.get("name", ""),
            "up_key": up_key,
            "up_name": up_name,
            "down_key": down_key,
            "down_name": down_name,
        })

    result.sort(key=lambda r: r["nature_id"])
    return result


def main():
    use_cache = "--cache" in sys.argv

    print("抓取/读取 Natures 模块...")
    wikitext = load_or_fetch(NATURES_PAGE, use_cache)

    print("解析性格数据...")
    rows = parse_natures(wikitext)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"完成：共 {len(rows)} 种性格。")
    print(f"输出文件：{OUT_CSV}")


if __name__ == "__main__":
    main()
