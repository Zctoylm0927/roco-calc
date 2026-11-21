#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用示例对局演示完整对局日志的推断结果。

用法:
    python battle_demo.py
    python battle_demo.py data/battle_example.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import roco_battle as rb

ROOT = Path(__file__).resolve().parent
DEFAULT_FILE = ROOT / "data" / "battle_example.json"


def _range_text(value, suffix=""):
    if value is None:
        return "—"
    if isinstance(value, dict):
        low = value.get("min")
        high = value.get("max")
        if low == high:
            return f"{low}{suffix}"
        return f"{low}～{high}{suffix}"
    return f"{value}{suffix}"


def _side_text(side):
    return {"our": "我方", "theirs": "对方"}.get(side, side)


def _action_text(action):
    if action is None:
        return "空"
    if action["type"] == "switch":
        return f"切换到第 {action['to_slot'] + 1} 只"
    if action["type"] == "charge":
        return "聚能"
    return f"使用 {action['skill']}"


def _event_text(event):
    kind = "伤害" if event.get("type") == "damage" else "生命变化"
    if event.get("matched"):
        text = f"{kind}：匹配成功"
        if event.get("kept") is not None:
            text += f"，剩 {event['kept']} 种"
        if event.get("message"):
            text += f"；{event['message']}"
        return text
    return f"{kind}：未匹配或未参与推断；{event.get('message', '')}"


def print_result(result):
    print(f"对局等级：{result['level']}")
    print(f"魔力值：我方 {result['magic_points']['our']}，对方 {result['magic_points']['opp']}")
    if result.get("result"):
        print(f"结果：{result['result']}")
    print()

    print("对方精灵：")
    for item in result["opponent_team"]:
        if not item.get("configured"):
            continue
        builds = item["builds"]
        stats = item["stats"]
        print(
            f"  第 {item['slot'] + 1} 只 {item['pet']}"
            f"{'（' + item['form'] + '）' if item.get('form') else ''}："
        )
        print(
            f"    可能 {builds['remaining']} / {builds['total']} 种，"
            f"{item['natures_remaining']} 种性格"
        )
        print(
            f"    生命 {_range_text(item.get('current_hp'))}，"
            f"显示 {_range_text(item.get('current_hp_percent'), '%')}"
        )
        print(
            f"    物攻 {_range_text(stats['atk'])}，物防 {_range_text(stats['def'])}，"
            f"魔攻 {_range_text(stats['spa'])}，魔防 {_range_text(stats['spd'])}，"
            f"速度 {_range_text(item.get('speed_after_buffs'))}"
        )
        if item.get("observed_skills"):
            print(f"    已见技能：{'、'.join(item['observed_skills'])}")
        print()

    print("回合：")
    for turn in result["turns"]:
        print(
            f"  第 {turn['turn']} 回合："
            f"我方 {_action_text(turn['our_action'])}，"
            f"对方 {_action_text(turn['opp_action'])}，"
            f"先手 {_side_text(turn['who_first']) if turn['who_first'] else '未填'}；"
            f"应对 {'是' if turn['counter'] else '否'}，"
            f"可推断速度 {'是' if turn['speed_inferable'] else '否'}"
        )
        for event in turn["events"]:
            print(f"    事件 {event['index'] + 1}：{_event_text(event)}")
        if turn["warnings"]:
            print("    提醒：")
            for warning in turn["warnings"]:
                print(f"      - {warning}")
        print()

    if result["warnings"]:
        print("整场提醒：")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    else:
        print("整场没有提醒。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="完整对局日志演示")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_FILE),
        help="对局 JSON 文件，默认 data/battle_example.json",
    )
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = rb.analyze_battle_log(payload)
    print(f"读取对局：{path}")
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
