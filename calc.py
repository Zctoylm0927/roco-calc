#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛克王国世界伤害计算器（命令行入口）

示例:
    python calc.py --attacker 岚鸟 --attacker-form 本来的样子 \
        --defender 奇丽花 --skill 扇风 \
        --attacker-talents "物攻=10" --defender-talents "物防=10" \
        --power 142.5

    python calc.py --attacker 岚鸟 --attacker-form 本来的样子 \
        --defender 奇丽花 --skill 扇风 --json

说明:
    - 默认按 60 级 PVP 计算，可用 --level 改等级。
    - 不填性格时按「不加不减」处理；不填天分时按全 0 处理。
    - 威力随规则变化的技能（如魔能爆、怨力打击）需要 --power 手动指定威力。
"""

import argparse
import json
import sys

import roco_calc as rc


def parse_talents(text):
    """把「物攻=10,速度=10」解析成字典。"""
    result = {}
    for chunk in text.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise argparse.ArgumentTypeError(
                "天分格式应为「物攻=10,速度=10」"
            )
        key, value = chunk.split("=", 1)
        try:
            value = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"天分数值“{value}”不是整数"
            )
        result[key.strip()] = value
    return result


def build_parser():
    parser = argparse.ArgumentParser(
        description="洛克王国世界伤害计算器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python calc.py --attacker 岚鸟 --attacker-form 本来的样子 "
            "--defender 奇丽花 --skill 扇风 --attacker-talents \"物攻=10\" "
            "--defender-talents \"物防=10\" --power 142.5\n"
        ),
    )

    parser.add_argument("--attacker", required=True, help="攻击方精灵名称或编号")
    parser.add_argument("--attacker-form", default=None, help="攻击方形态（同名多形态时必填）")
    parser.add_argument("--defender", required=True, help="受击方精灵名称或编号")
    parser.add_argument("--defender-form", default=None, help="受击方形态（同名多形态时必填）")
    parser.add_argument("--skill", required=True, help="技能名称")

    parser.add_argument("--attacker-nature", default=None, help="攻击方性格，例如 固执；不填表示不加不减")
    parser.add_argument("--defender-nature", default=None, help="受击方性格；不填表示不加不减")
    parser.add_argument("--attacker-talents", type=parse_talents, default=None,
                        help="攻击方天分，例如 物攻=10,速度=10")
    parser.add_argument("--defender-talents", type=parse_talents, default=None,
                        help="受击方天分，例如 物防=10")
    parser.add_argument("--level", type=int, default=60, help="等级，默认 60")

    parser.add_argument("--power", type=float, default=None,
                        help="手动指定基础威力；不填则使用技能表里的威力")
    parser.add_argument("--power-bonus", type=float, default=0.0,
                        help="固定威力加成，默认 0")
    parser.add_argument("--power-percent", type=float, default=0.0,
                        help="威力百分比加成，填 10 表示再加百分之十")
    parser.add_argument("--damage-only-power-bonus", type=float, default=0.0,
                        help="只影响伤害的固定威力加成，默认 0")
    parser.add_argument("--damage-only-power-percent", type=float, default=0.0,
                        help="只影响伤害的威力百分比加成，默认 0")

    parser.add_argument("--attack-mod", type=float, default=0.0,
                        help="攻击方能力等级百分比，例如 50 表示增攻百分之五十")
    parser.add_argument("--defense-mod", type=float, default=0.0,
                        help="受击方能力等级百分比，例如 -50 表示减防百分之五十")
    parser.add_argument("--damage-reduction", type=float, default=0.0,
                        help="减伤百分比，例如 30 表示减少百分之三十")
    parser.add_argument("--damage-multiplier", type=float, default=100.0,
                        help="最终伤害乘区百分比，默认 100")
    parser.add_argument("--hits", type=int, default=1, help="连击次数，默认 1")
    parser.add_argument("--misc-multiplier", type=float, default=1.0,
                        help="其他乘区，默认 1")
    parser.add_argument("--ignore-type-resistance", action="store_true",
                        help="忽略属性抵抗（抵抗按 ×1 计算）")
    parser.add_argument("--json", action="store_true",
                        help="输出完整 JSON，便于程序调用")
    return parser


def _fmt(value):
    """把 2.0 这类浮点数显示成 2，把 142.5 保留成 142.5。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:g}" if isinstance(value, float) else str(value)


def _panel_text(stats):
    return " / ".join(
        f"{rc.STAT_NAMES[key]} {stats[key]}" for key in rc.STAT_KEYS
    )


def _nature_text(nature):
    return nature["name"] if nature else "无（不加不减）"


def _talents_text(talents):
    parts = [
        f"{rc.STAT_NAMES[key]} {value}"
        for key, value in talents.items()
        if value
    ]
    return " / ".join(parts) if parts else "全 0"


def _pet_title(panel):
    pet = panel["pet"]
    return pet["name"] + (f"（{pet['form']}）" if pet["form"] else "")


def format_result(result):
    """把计算结果排版成中文文本。"""
    attacker = result["attacker"]
    defender = result["defender"]
    skill = result["skill"]

    lines = ["=" * 52]
    lines.append(f"攻击方：{_pet_title(attacker)}")
    lines.append(f"  属性：{'、'.join(attacker['pet']['types'])}")
    lines.append(
        f"  等级：{result['level']}    "
        f"性格：{_nature_text(attacker['nature'])}    "
        f"天分：{_talents_text(attacker['talents'])}"
    )
    lines.append(f"  面板：{_panel_text(attacker['stats'])}")
    lines.append("")

    manual_power = result["base_power"] != (skill.get("power") or 0)
    power_note = "（手动指定）" if manual_power else ""
    energy = skill.get("energy")
    energy_text = f"    能耗：{energy}" if energy is not None else ""
    lines.append(f"技能：{skill['name']}")
    lines.append(
        f"  属性：{skill['element']}    "
        f"类型：{skill['damage_class']}    "
        f"基础威力：{_fmt(result['base_power'])}{power_note}{energy_text}"
    )
    if skill.get("power_text"):
        lines.append(f"  威力备注：{skill['power_text']}")
    lines.append(f"  有效威力：{_fmt(result['effective_power'])}")
    lines.append(f"  本系加成：×{_fmt(result['stab'])}")
    lines.append(f"  属性克制：×{_fmt(result['type_multiplier'])}")
    if result["ability_multiplier"] != 1:
        lines.append(f"  攻防等级：×{_fmt(result['ability_multiplier'])}")
    if result["damage_reduction_multiplier"] != 1:
        lines.append(
            f"  减伤乘区：×{_fmt(result['damage_reduction_multiplier'])}"
        )
    lines.append(f"  显示威力：{result['display_power']}")
    lines.append("")

    lines.append(f"受击方：{_pet_title(defender)}")
    lines.append(f"  属性：{'、'.join(defender['pet']['types'])}")
    lines.append(
        f"  等级：{result['level']}    "
        f"性格：{_nature_text(defender['nature'])}    "
        f"天分：{_talents_text(defender['talents'])}"
    )
    lines.append(f"  面板：{_panel_text(defender['stats'])}")
    lines.append(
        f"  对应防御：{rc.STAT_NAMES[result['defense_key']]} "
        f"{result['defender_defense']}"
    )
    lines.append("")

    lines.append("结果：")
    lines.append(
        f"  单次伤害：{result['damage_per_hit']}    "
        f"连击：{result['hit_count']}    "
        f"最终乘区：×{_fmt(result['damage_multiplier'])}"
    )
    lines.append(
        f"  总伤害：{result['damage']}"
        f"（占最大生命 {result['damage_percent']:.1f}%）"
    )
    verdict = "可以击倒" if result["is_knockout"] else "不能击倒"
    lines.append(f"  {verdict}（最大生命 {result['defender_hp']}）")
    lines.append("=" * 52)
    return "\n".join(lines)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = rc.calculate_matchup(
            args.attacker,
            args.defender,
            args.skill,
            attacker_form=args.attacker_form,
            defender_form=args.defender_form,
            attacker_nature=args.attacker_nature,
            defender_nature=args.defender_nature,
            attacker_talents=args.attacker_talents,
            defender_talents=args.defender_talents,
            level=args.level,
            power=args.power,
            power_bonus=args.power_bonus,
            power_percent=args.power_percent,
            damage_only_power_bonus=args.damage_only_power_bonus,
            damage_only_power_percent=args.damage_only_power_percent,
            attack_modifier_percent=args.attack_mod,
            defense_modifier_percent=args.defense_mod,
            damage_reduction_percent=args.damage_reduction,
            damage_multiplier_percent=args.damage_multiplier,
            hit_count=args.hits,
            misc_multiplier=args.misc_multiplier,
            ignore_type_resistance=args.ignore_type_resistance,
        )
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
