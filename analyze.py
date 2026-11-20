#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
范围推断的命令行演示（验证 roco_analysis.py 用）。

示例:
    # 初始范围：龙息帕尔魔防 145～217，气泡伤害 140～210
    python analyze.py --our 水灵 --nature 聪明 --talent 魔攻=10 \
        --opponent 龙息帕尔 --skill 气泡

    # 记录“雨天打了 341”后，魔防锁定 156
    python analyze.py --our 水灵 --nature 聪明 --talent 魔攻=10 \
        --opponent 龙息帕尔 --skill 气泡 --weather 雨天 --observe 341

    # 再记录“打掉 195 血后对方显示 50%”，生命锁定 391
    python analyze.py --our 水灵 --nature 聪明 --talent 魔攻=10 \
        --opponent 龙息帕尔 --skill 气泡 \
        --observe hp:50:195

说明:
    - 战斗记录按 --observe 的填写顺序处理。
    - 伤害记录可以写成整数；生命百分比记录写成 hp:百分比:累计伤害。
    - 记录默认沿用当前天气、增减益、星陨层数；暂不支持单条记录覆盖。
"""

import argparse
import json
import sys

import roco_analysis as ra
import roco_calc as rc


def parse_talents(text):
    """把「魔攻=10,速度=10」解析成字典。"""
    result = {}
    for chunk in text.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise argparse.ArgumentTypeError("天分格式应为「魔攻=10,速度=10」")
        key, value = chunk.split("=", 1)
        try:
            result[key.strip()] = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"天分数值“{value}”不是整数")
    return result


def parse_buffs(text):
    """把「魔攻=2,速度=-1」解析成字典。"""
    result = {}
    for chunk in text.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise argparse.ArgumentTypeError("增减益格式应为「魔攻=2,速度=-1」")
        key, value = chunk.split("=", 1)
        try:
            result[key.strip()] = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"增减益层数“{value}”不是整数")
    return result


def parse_observe(text):
    """解析一条战斗记录。

    - 「341」表示造成 341 点伤害。
    - 「hp:50:195」表示打完后对方显示 50%，累计伤害 195。
    """
    raw = str(text).strip()
    lowered = raw.lower()
    if lowered.startswith(("hp:", "生命:")):
        body = raw.split(":", 1)[1]
        parts = body.replace("：", ":").split(":")
        if len(parts) != 2:
            raise argparse.ArgumentTypeError(
                "生命百分比记录格式应为 hp:50:195（百分比:累计伤害）"
            )
        try:
            percent = int(parts[0])
            total_damage = int(parts[1])
        except ValueError:
            raise argparse.ArgumentTypeError(
                "生命百分比和累计伤害都必须是整数"
            )
        return {
            "type": "hp_percent",
            "hp_percent": percent,
            "total_damage": total_damage,
        }
    try:
        damage = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "伤害记录必须是整数；生命百分比请写成 hp:50:195"
        )
    return {"type": "damage", "attacker": "our", "damage": damage}


def build_parser():
    parser = argparse.ArgumentParser(
        description="洛克王国世界：对方未知性格/天分的伤害范围推断",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python analyze.py --our 水灵 --nature 聪明 --talent 魔攻=10 "
            "--opponent 龙息帕尔 --skill 气泡\n"
            "  python analyze.py --our 水灵 --nature 聪明 --talent 魔攻=10 "
            "--opponent 龙息帕尔 --skill 气泡 --weather 雨天 --observe 341\n"
        ),
    )

    parser.add_argument("--our", required=True, help="我方精灵名称或编号")
    parser.add_argument("--our-form", default=None, help="我方形态")
    parser.add_argument("--nature", default=None, help="我方性格，例如 聪明")
    parser.add_argument("--talent", type=parse_talents, default=None,
                        help="我方天分，例如 魔攻=10")
    parser.add_argument("--our-buffs", type=parse_buffs, default=None,
                        help="我方增减益层数，例如 魔攻=2")

    parser.add_argument("--opponent", required=True, help="对方精灵名称或编号")
    parser.add_argument("--opponent-form", default=None, help="对方形态")
    parser.add_argument("--opponent-buffs", type=parse_buffs, default=None,
                        help="对方增减益层数，例如 魔防=-1")

    parser.add_argument("--skill", required=True, help="我方使用的技能名称")
    parser.add_argument("--weather", default=None, help="天气，例如 雨天")
    parser.add_argument("--starfall-layers", type=int, default=0,
                        help="对方身上的星陨层数（0～99）")
    parser.add_argument("--level", type=int, default=60, help="等级，默认 60")

    parser.add_argument("--observe", type=parse_observe, action="append",
                        default=None,
                        help="战斗记录，可重复：341（伤害）或 hp:50:195（生命百分比）")
    parser.add_argument("--hp-percent-rounding", default="round",
                        choices=ra.HP_PERCENT_ROUNDING_MODES,
                        help="生命百分比取整方式，默认 round")

    parser.add_argument("--hits", type=int, default=1, help="连击次数，默认 1")
    parser.add_argument("--damage-reduction", type=float, default=0.0,
                        help="减伤百分比")
    parser.add_argument("--damage-multiplier", type=float, default=100.0,
                        help="最终伤害乘区百分比，默认 100")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    return parser


def _range_text(item):
    if item["min"] == item["max"]:
        return f"{item['min']}"
    return f"{item['min']}～{item['max']}"


def _record_text(result):
    kind = result["type"]
    if kind == "damage":
        what = "伤害记录"
    elif kind == "hp_percent":
        what = "生命百分比记录"
    else:
        what = "记录"
    status = (
        f"对上了，剩 {result['kept']:,} 种整体组合"
        if result["matched"]
        else f"没有对上，已跳过（{result['message']}）"
    )
    return f"  {result['index'] + 1}. {what}：{status}"


def format_result(result):
    opponent = result["opponent"]
    damage = result["damage"]
    lines = ["=" * 56]
    title = opponent["pet"] + (
        f"（{opponent['form']}）" if opponent["form"] else ""
    )
    lines.append(f"对方：{title}（{opponent['level']} 级，性格和天分未知）")
    builds = opponent["builds"]
    lines.append(
        f"  可能组合：{builds['remaining']:,} / {builds['total']:,}"
        f"    可能性格：{opponent['natures_remaining']} 种"
    )
    for key in rc.STAT_KEYS:
        item = opponent["stats"][key]
        count = len(item["possible_values"])
        if count == 1:
            lines.append(f"  {rc.STAT_NAMES[key]}：{item['min']}（已锁定）")
        else:
            lines.append(
                f"  {rc.STAT_NAMES[key]}：{_range_text(item)}"
                f"（{count} 种可能取值）"
            )
    if opponent["observations"]:
        lines.append("战斗记录：")
        lines.extend(_record_text(item) for item in opponent["observations"])
    for warning in opponent["warnings"]:
        lines.append(f"  提示：{warning}")
    lines.append("")

    lines.append(f"技能：{damage['skill']}")
    lines.append(
        f"  伤害范围：{damage['min']}～{damage['max']}"
        f"（按剩余候选的{rc.STAT_NAMES[damage['defense_key']]}计算）"
    )
    lines.append(
        f"    {rc.STAT_NAMES[damage['defense_key']]}最高 "
        f"{damage['min_case_defense']} → 伤害 {damage['min']}"
    )
    lines.append(
        f"    {rc.STAT_NAMES[damage['defense_key']]}最低 "
        f"{damage['max_case_defense']} → 伤害 {damage['max']}"
    )
    lines.append(
        f"  占对方最大生命：{damage['damage_percent_min']}%～"
        f"{damage['damage_percent_max']}%"
    )
    verdict = {
        "certain": "一定击倒",
        "possible": "可能击倒",
        "impossible": "不能击倒",
    }[damage["knockout"]]
    lines.append(f"  击倒判断：{verdict}")
    lines.append("=" * 56)
    return "\n".join(lines)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    state = {
        "our_pet": {
            "name": args.our,
            "form": args.our_form,
            "nature": args.nature,
            "talents": args.talent,
            "buffs": args.our_buffs,
        },
        "opponent_pet": {
            "name": args.opponent,
            "form": args.opponent_form,
            "buffs": args.opponent_buffs,
        },
        "skill": args.skill,
        "weather": args.weather,
        "starfall_layers": args.starfall_layers,
        "level": args.level,
        "hp_percent_rounding": args.hp_percent_rounding,
        "hits": args.hits,
        "damage_reduction_percent": args.damage_reduction,
        "damage_multiplier_percent": args.damage_multiplier,
        "observations": args.observe or [],
    }

    try:
        result = ra.analyze_battle(state)
    except rc.RocoCalcError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
