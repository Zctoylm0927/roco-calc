#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界（roco）可学习技能表爬取脚本

数据来源: wiki.biligame.com/nrc 的两个 Lua 数据模块
    - Module:Pets/data/Learnsets  每只精灵的学习表
    - Module:Pets/data/Catalog    用来把学习表挂到 pets.csv 的精灵行上

输出: data/learnsets.csv

每行是「一只精灵 + 一个技能」，同一技能来自多个来源时合并成一行：
    pet_id          目录模块内的精灵 ID（如 pet_000005）
    number          图鉴编号
    name            精灵名称
    form            形态（与 data/pets.csv 一致）
    stage           进化阶段（与 data/pets.csv 一致）
    skill_id        技能模块 ID
    skill_name      技能中文名
    category        攻击 / 状态 / 防御 / 特性
    element         技能属性
    damage_class    物攻 / 魔攻（仅攻击技能）
    power           基础威力（仅攻击技能）
    sources         学习来源，多个用 | 分隔：native / blood / stone / feature
                    native = 升级学习；blood = 血脉技能；stone = 技能石；
                    feature = 精灵自带特性技能
    level           升级/血脉学习的最低等级（没有等级信息时为空）
    blood           血脉技能对应的属性，多个用 | 分隔

只保留 data/skills.csv 里能找到的技能；找不到的技能 ID 会在运行结束时列出。
本表包含非攻击技能，页面显示技能下拉时再按 category 过滤。

用法:
    python crawl_learnsets.py            联网抓取并生成 CSV
    python crawl_learnsets.py --cache    使用本地缓存（离线重跑）
"""

import csv
import os
import sys
from collections import Counter, defaultdict

# 复用精灵爬虫的 Lua 表解析器与 MediaWiki 抓取/缓存逻辑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_pets import LuaParser, load_or_fetch  # noqa: E402

CATALOG_PAGE = "Module:Pets/data/Catalog"
LEARNSETS_PAGE = "Module:Pets/data/Learnsets"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PETS_CSV = os.path.join(BASE_DIR, "data", "pets.csv")
SKILLS_CSV = os.path.join(BASE_DIR, "data", "skills.csv")
OUT_CSV = os.path.join(BASE_DIR, "data", "learnsets.csv")

FIELD_NAMES = [
    "pet_id", "number", "name", "form", "stage",
    "skill_id", "skill_name", "category", "element",
    "damage_class", "power", "sources", "level", "blood",
]

SOURCE_ORDER = ("native", "blood", "stone", "feature")
BLOOD_ORDER = (
    "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
    "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻",
)


def _strip_leading_comments(text):
    """模块开头有 Lua 注释行，LuaParser 不处理注释，先去掉。"""
    lines = text.splitlines()
    while lines and lines[0].lstrip().startswith("--"):
        lines.pop(0)
    return "\n".join(lines)


def parse_catalog(text):
    """解析 Catalog，返回 {pet_id: {number,name,form,stage,learnset_id}}。"""
    root = LuaParser(_strip_leading_comments(text)).parse()
    entries = {}
    for pet_id, raw in root.items():
        if not isinstance(raw, dict):
            continue
        entries[pet_id] = {
            "id": raw.get("id", pet_id),
            "number": str(raw.get("number", "")),
            "name": raw.get("name", ""),
            "form": raw.get("form") or "",
            "stage": str(raw.get("stage", "")),
            "learnset_id": raw.get("learnset_id", ""),
        }
    return entries


def parse_learnsets(text):
    """解析 Learnsets 模块，返回 {learnset_id: 原始字典}。"""
    root = LuaParser(_strip_leading_comments(text)).parse()
    return {
        learnset_id: raw
        for learnset_id, raw in root.items()
        if isinstance(raw, dict)
    }


def read_pets(path=PETS_CSV):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_skills(path=SKILLS_CSV):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {row["skill_id"]: row for row in csv.DictReader(f)}


def build_indexes(catalog):
    """为「pets.csv 的一行 → Catalog 条目」建立三级索引。"""
    exact = defaultdict(list)
    by_number_name_stage = defaultdict(list)
    by_number_name = defaultdict(list)
    for entry in catalog.values():
        exact[
            (entry["number"], entry["name"], entry["form"], entry["stage"])
        ].append(entry)
        by_number_name_stage[
            (entry["number"], entry["name"], entry["stage"])
        ].append(entry)
        by_number_name[(entry["number"], entry["name"])].append(entry)
    return {
        "exact": exact,
        "stage": by_number_name_stage,
        "name": by_number_name,
    }


def _unique_learnset_entry(entries):
    """候选条目的学习表都相同时，返回其中一个；否则返回 None。"""
    learnset_ids = {
        entry["learnset_id"] for entry in entries if entry.get("learnset_id")
    }
    if len(learnset_ids) != 1:
        return None
    learnset_id = next(iter(learnset_ids))
    for entry in entries:
        if entry["learnset_id"] == learnset_id:
            return entry
    return None


def match_pet(row, indexes):
    """把 pets.csv 的一行匹配到 Catalog 条目。

    先按「编号 + 名称 + 形态 + 阶段」精确匹配；老数据里少数基础形态的
    形态名已经变了（例如从空字符串变成「本来的样子」），这时退回到
    「编号 + 名称 + 阶段」，要求候选条目的学习表完全相同，避免选错形态。
    返回 (条目, 匹配方式)；匹配不到返回 (None, None)。
    """
    key = (row["number"], row["name"], row["form"], str(row["stage"]))
    exact = indexes["exact"].get(key)
    if exact:
        return exact[0], "exact"

    key = (row["number"], row["name"], str(row["stage"]))
    entry = _unique_learnset_entry(indexes["stage"].get(key, []))
    if entry is not None:
        return entry, "same_number_name_stage"

    key = (row["number"], row["name"])
    entry = _unique_learnset_entry(indexes["name"].get(key, []))
    if entry is not None:
        return entry, "same_number_name"

    return None, None


def collect_pet_skills(learnset, skills):
    """汇总一只精灵的学习表，返回 (按技能合并的记录, 缺失技能计数)。

    记录格式:
        {skill_id: {"sources": set(), "levels": [..], "bloods": [..]}}
    """
    records = {}
    missing = Counter()

    def add(skill_id, source, level=None, blood=None):
        if not skill_id:
            return
        record = records.setdefault(
            skill_id, {"sources": set(), "levels": [], "bloods": []}
        )
        record["sources"].add(source)
        if level is not None:
            record["levels"].append(level)
        if blood and blood not in record["bloods"]:
            record["bloods"].append(blood)

    for item in learnset.get("native_skills", []) or []:
        if isinstance(item, dict):
            add(item.get("skill"), "native", item.get("level"))

    for item in learnset.get("blood_skills", []) or []:
        if isinstance(item, dict):
            add(item.get("skill"), "blood", item.get("level"), item.get("blood"))

    for skill_id in learnset.get("skill_stones", []) or []:
        if isinstance(skill_id, str):
            add(skill_id, "stone")

    add(learnset.get("feature_skill"), "feature")

    for skill_id in list(records):
        if skill_id not in skills:
            missing[skill_id] += 1
            del records[skill_id]

    return records, missing


def _blood_sort_key(blood):
    try:
        return (0, BLOOD_ORDER.index(blood))
    except ValueError:
        return (1, blood)


def _skill_sort_key(skill_id):
    suffix = skill_id.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return (0, int(suffix))
    return (1, skill_id)


def build_rows(pets, catalog, learnsets, skills):
    """生成 learnsets.csv 的行，并返回统计信息。"""
    indexes = build_indexes(catalog)
    rows = []
    unmatched = []
    missing_learnsets = []
    missing_skill_refs = Counter()
    used_pet_ids = set()
    attack_counts = []
    pets_without_attack = []

    for row in pets:
        entry, _match_kind = match_pet(row, indexes)
        if entry is None:
            unmatched.append(row)
            continue
        learnset = learnsets.get(entry["learnset_id"])
        if learnset is None:
            missing_learnsets.append((row, entry["learnset_id"]))
            continue

        used_pet_ids.add(entry["id"])
        records, missing = collect_pet_skills(learnset, skills)
        missing_skill_refs.update(missing)

        attack_count = sum(
            1 for skill_id in records
            if skills[skill_id].get("category") == "攻击"
        )
        attack_counts.append(attack_count)
        if attack_count == 0:
            pets_without_attack.append((row["number"], row["name"], row["form"]))

        for skill_id in sorted(records, key=_skill_sort_key):
            record = records[skill_id]
            skill = skills[skill_id]
            levels = [level for level in record["levels"] if level is not None]
            rows.append({
                "pet_id": entry["id"],
                "number": row["number"],
                "name": row["name"],
                "form": row["form"],
                "stage": row["stage"],
                "skill_id": skill_id,
                "skill_name": skill["name"],
                "category": skill["category"],
                "element": skill["element"],
                "damage_class": skill["damage_class"],
                "power": skill["power"],
                "sources": "|".join(
                    source for source in SOURCE_ORDER
                    if source in record["sources"]
                ),
                "level": min(levels) if levels else "",
                "blood": "|".join(
                    sorted(record["bloods"], key=_blood_sort_key)
                ),
            })

    unused_catalog = [
        entry for pet_id, entry in catalog.items()
        if pet_id not in used_pet_ids
    ]

    stats = {
        "unmatched": unmatched,
        "missing_learnsets": missing_learnsets,
        "missing_skill_refs": missing_skill_refs,
        "unused_catalog": unused_catalog,
        "attack_counts": attack_counts,
        "pets_without_attack": pets_without_attack,
    }
    return rows, stats


def main():
    use_cache = "--cache" in sys.argv

    print("拉取/读取 Catalog 模块...")
    catalog_text = load_or_fetch(CATALOG_PAGE, use_cache)
    print("拉取/读取 Learnsets 模块...")
    learnsets_text = load_or_fetch(LEARNSETS_PAGE, use_cache)

    print("解析数据...")
    catalog = parse_catalog(catalog_text)
    learnsets = parse_learnsets(learnsets_text)
    pets = read_pets()
    skills = read_skills()

    rows, stats = build_rows(pets, catalog, learnsets, skills)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerows(rows)

    unique_skills = {row["skill_id"] for row in rows}
    attack_rows = sum(1 for row in rows if row["category"] == "攻击")
    source_counts = Counter()
    for row in rows:
        for source in row["sources"].split("|"):
            source_counts[source] += 1

    covered = len(pets) - len(stats["unmatched"]) - len(stats["missing_learnsets"])
    print(
        f"完成：{covered} / {len(pets)} 只精灵匹配到学习表，"
        f"生成 {len(rows)} 行（{len(unique_skills)} 个不同技能，"
        f"其中攻击技能 {attack_rows} 行）。"
    )
    if stats["attack_counts"]:
        print(
            "每只精灵的攻击技能数量："
            f"最少 {min(stats['attack_counts'])} 个，"
            f"最多 {max(stats['attack_counts'])} 个。"
        )
    print(
        "学习来源行数："
        + "，".join(
            f"{source} {source_counts[source]}"
            for source in SOURCE_ORDER
        )
        + "（同一技能来自多个来源时会在多列各算一次）。"
    )

    if stats["unmatched"]:
        print(f"警告：{len(stats['unmatched'])} 只精灵在 Catalog 中找不到对应条目：")
        for row in stats["unmatched"][:20]:
            print(f"  {row['number']} {row['name']}（{row['form'] or '无形态'}）")
    if stats["missing_learnsets"]:
        print(f"警告：{len(stats['missing_learnsets'])} 只精灵的学习表 ID 不存在：")
        for row, learnset_id in stats["missing_learnsets"][:20]:
            print(f"  {row['number']} {row['name']} → {learnset_id}")
    if stats["missing_skill_refs"]:
        total = sum(stats["missing_skill_refs"].values())
        print(
            f"提示：{len(stats['missing_skill_refs'])} 个技能 ID 在 skills.csv 中找不到，"
            f"共 {total} 条引用，已跳过。"
        )
        for skill_id, count in stats["missing_skill_refs"].most_common(10):
            print(f"  {skill_id}（{count} 条）")
    if stats["unused_catalog"]:
        print(
            f"提示：Catalog 有 {len(stats['unused_catalog'])} 个条目不在 pets.csv 中，"
            "未写入本表（通常是新精灵或新形态，需要先更新精灵表）。"
        )
        for entry in stats["unused_catalog"][:15]:
            print(
                f"  {entry['number']} {entry['name']}"
                f"（{entry['form'] or '无形态'}，{entry['stage']} 阶段）"
            )
    if stats["pets_without_attack"]:
        print(
            f"提示：{len(stats['pets_without_attack'])} 只精灵没有任何攻击技能："
            + "、".join(
                f"{number} {name}" for number, name, _form
                in stats["pets_without_attack"][:10]
            )
        )

    print(f"输出文件：{OUT_CSV}")

    if stats["unmatched"] or stats["missing_learnsets"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
