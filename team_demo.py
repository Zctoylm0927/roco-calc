#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""6 对 6 后端演示。

不需要网页，直接运行：
    python team_demo.py

演示内容：
    1. 水灵气泡打帕尔 195，打完剩 50%；
    2. 帕尔生命变成 80%，实际回血 +116；
    3. 帕尔用龙之利爪打我方 160，我方剩 146。

第二只对方精灵（奇丽花）不参与记录，用来确认不同位置互不影响。
"""

import roco_team as rt


def build_state(records):
    return {
        "level": 60,
        "weather": None,
        "our_team": [
            {
                "pet": "水灵",
                "nature": "聪明",
                "talents": {"spa": 10},
                "skills": ["气泡", "水炮", "天洪", "水弹枪"],
                "current_hp": 306,
            },
        ],
        "opponent_team": [
            {
                "pet": "龙息帕尔",
                "skills": ["龙之利爪", "升龙咆哮"],
            },
            {
                "pet": "奇丽花",
            },
        ],
        "active_our_slot": 0,
        "active_opponent_slot": 0,
        "records": records,
    }


RECORDS = [
    {
        "type": "damage",
        "attacker_side": "our",
        "attacker_slot": 0,
        "defender_side": "theirs",
        "defender_slot": 0,
        "skill": "气泡",
        "damage": 195,
        "hp_percent": 50,
    },
    {
        "type": "hp_change",
        "side": "theirs",
        "slot": 0,
        "hp_percent": 80,
        "hp_delta": 116,
    },
    {
        "type": "damage",
        "attacker_side": "theirs",
        "attacker_slot": 0,
        "defender_side": "our",
        "defender_slot": 0,
        "skill": "龙之利爪",
        "damage": 160,
        "remaining_hp": 146,
    },
]


def number_range(value):
    if value["min"] == value["max"]:
        return str(value["min"])
    return f"{value['min']}～{value['max']}"


def show_opponent(result, index):
    opponent = result["opponent_team"][index]
    if not opponent["configured"]:
        print(f"  对方位置 {index + 1}：未选择精灵")
        return
    builds = opponent["builds"]
    print(
        f"  对方位置 {index + 1}：{opponent['pet']}，"
        f"{builds['remaining']:,} / {builds['total']:,} 种可能，"
        f"{opponent['natures_remaining']} 种性格"
    )
    print(
        "    生命 {}～{}；魔防 {}～{}；物攻 {}～{}".format(
            opponent["stats"]["hp"]["min"],
            opponent["stats"]["hp"]["max"],
            opponent["stats"]["spd"]["min"],
            opponent["stats"]["spd"]["max"],
            opponent["stats"]["atk"]["min"],
            opponent["stats"]["atk"]["max"],
        )
    )
    print(
        "    当前生命 {}（显示 {}%）".format(
            number_range(opponent["current_hp"]),
            number_range(opponent["current_hp_percent"]),
        )
    )


def show_active_skills(result):
    active = result["active"]
    if active is None:
        return
    our = result["our_team"][active["our_slot"]]
    opponent = result["opponent_team"][active["opponent_slot"]]
    print(
        f"  我方 {our['pet']}（生命 {number_range(our['current_hp'])}）"
        f" 对 对方 {opponent['pet']}"
    )
    print("  我方技能：")
    for skill in active["our_skills"]:
        if not skill["available"]:
            print(f"    {skill['skill']}：{skill['reason']}")
            continue
        print(
            "    {}：伤害 {}；对方剩余生命 {}%".format(
                skill["skill"],
                number_range(skill["damage"]),
                number_range(skill["remaining_hp_percent"]),
            )
        )
    print("  对方技能：")
    for skill in active["opponent_skills"]:
        if not skill["available"]:
            print(f"    {skill['skill']}：{skill['reason']}")
            continue
        print(
            "    {}：伤害 {}；我方剩余生命 {}".format(
                skill["skill"],
                number_range(skill["damage"]),
                number_range(skill["our_remaining_hp"]),
            )
        )


def show_step(title, records):
    print(f"\n=== {title} ===")
    result = rt.analyze_team(build_state(records))
    show_opponent(result, 0)
    show_opponent(result, 1)
    if result["records"]:
        record = result["records"][-1]
        print(
            "  最后一条记录：{}，{}".format(
                "对上了" if record["matched"] else "没有对上",
                record["message"] or "没有额外提示",
            )
        )
    if result["warnings"]:
        for warning in result["warnings"]:
            print(f"  提示：{warning}")
    show_active_skills(result)
    return result


def main():
    print("洛克王国世界 PVP：6 对 6 后端演示")
    print("我方水灵（聪明、魔攻天分 10）对龙息帕尔、奇丽花")
    print("我方水灵当前生命：306 / 383（具体数字，不使用百分比）")
    print("下面“技能”里的伤害，是从当前状态再打一次的预测，不是历史记录。")

    initial = show_step("初始状态", [])
    print(
        "\n初始核对的数字：帕尔 {} 种可能，生命 {}～{}，魔防 {}～{}。".format(
            initial["opponent_team"][0]["builds"]["remaining"],
            initial["opponent_team"][0]["stats"]["hp"]["min"],
            initial["opponent_team"][0]["stats"]["hp"]["max"],
            initial["opponent_team"][0]["stats"]["spd"]["min"],
            initial["opponent_team"][0]["stats"]["spd"]["max"],
        )
    )

    first = show_step("记录 1：水灵气泡打帕尔 195，打完剩 50%", RECORDS[:1])
    print(
        "\n核对：帕尔应剩 4,416 种、12 种性格，生命 391，魔防 156。"
    )
    print(
        "      实际：{} 种、{} 种性格，生命 {}，魔防 {}。".format(
            first["opponent_team"][0]["builds"]["remaining"],
            first["opponent_team"][0]["natures_remaining"],
            first["opponent_team"][0]["stats"]["hp"]["min"],
            first["opponent_team"][0]["stats"]["spd"]["min"],
        )
    )

    second = show_step(
        "记录 2：帕尔生命变成 80%，实际回血 +116", RECORDS[:2]
    )
    print(
        "\n核对：帕尔当前生命应锁定 312（显示 80%），可能组合仍是 4,416。"
    )
    print(
        "      实际：当前生命 {}，{} 种可能。".format(
            number_range(second["opponent_team"][0]["current_hp"]),
            second["opponent_team"][0]["builds"]["remaining"],
        )
    )

    third = show_step(
        "记录 3：帕尔用龙之利爪打我方 160，我方剩 146", RECORDS
    )
    print(
        "\n核对：帕尔应剩 366 种、6 种性格，物攻 223；"
        "我方当前生命 146（具体数字）。"
    )
    print(
        "      实际：{} 种、{} 种性格，物攻 {}，我方生命 {}。".format(
            third["opponent_team"][0]["builds"]["remaining"],
            third["opponent_team"][0]["natures_remaining"],
            third["opponent_team"][0]["stats"]["atk"]["min"],
            number_range(third["our_team"][0]["current_hp"]),
        )
    )
    print(
        "      第二只对方精灵（奇丽花）仍是 {} 种可能，说明两只互不影响。".format(
            third["opponent_team"][1]["builds"]["remaining"]
        )
    )
    print("\n演示结束。以上数字都由 roco_team.analyze_team() 计算。")


if __name__ == "__main__":
    main()
