#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整对局日志的测试。"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import roco_battle as rb  # noqa: E402
import roco_skill_rules as rsr  # noqa: E402


def base_payload():
    return {
        "version": 1,
        "initial": {
            "our_team": [
                {
                    "pet": "水灵",
                    "nature": "聪明",
                    "talents": {"spa": 10},
                    "skills": ["气泡", "水炮"],
                    "energy": 10,
                }
            ],
            "opponent_team": [
                {
                    "pet": "龙息帕尔",
                    "suspected_skills": ["龙之利爪"],
                    "energy": 10,
                }
            ],
            "active_our": 0,
            "active_opp": 0,
        },
        "turns": [
            {
                "our_action": {
                    "type": "skill",
                    "slot": 0,
                    "skill": "气泡",
                },
                "opp_action": {
                    "type": "skill",
                    "slot": 0,
                    "skill": "龙之利爪",
                },
                "who_first": "opp",
                "counter": False,
                "speed_inferable": True,
                "events": [
                    {
                        "type": "damage",
                        "source_side": "theirs",
                        "source_slot": 0,
                        "target_side": "our",
                        "target_slot": 0,
                        "skill": "龙之利爪",
                        "total_damage": 160,
                        "hits": 1,
                        "hp_after": {
                            "side": "our",
                            "slot": 0,
                            "hp": 223,
                        },
                        "context": {
                            "weather": None,
                            "our_marks": None,
                            "opp_marks": None,
                            "our_active": {
                                "slot": 0,
                                "hp": 383,
                                "energy": 10,
                                "buffs": None,
                                "statuses": [],
                            },
                            "opp_active": {
                                "slot": 0,
                                "hp_percent": 100,
                                "energy": 10,
                                "buffs": None,
                                "statuses": [],
                            },
                        },
                    },
                    {
                        "type": "damage",
                        "source_side": "our",
                        "source_slot": 0,
                        "target_side": "theirs",
                        "target_slot": 0,
                        "skill": "气泡",
                        "total_damage": 195,
                        "hits": 1,
                        "hp_after": {
                            "side": "theirs",
                            "slot": 0,
                            "hp_percent": 50,
                        },
                        "context": {
                            "weather": None,
                            "our_marks": None,
                            "opp_marks": None,
                            "our_active": {
                                "slot": 0,
                                "hp": 223,
                                "energy": 10,
                                "buffs": None,
                                "statuses": [],
                            },
                            "opp_active": {
                                "slot": 0,
                                "hp_percent": 100,
                                "energy": 10,
                                "buffs": None,
                                "statuses": [],
                            },
                        },
                    },
                ],
                "replacements": {"our": None, "opp": None},
                "snapshot_after": {
                    "active_our": 0,
                    "active_opp": 0,
                    "weather": None,
                    "our_marks": None,
                    "opp_marks": None,
                    "magic_points": {"our": 4, "opp": 4},
                    "our_pets": [
                        {
                            "hp": 223,
                            "energy": 7,
                            "buffs": None,
                            "statuses": [],
                        }
                    ],
                    "opp_pets": [
                        {
                            "hp_percent": 50,
                            "energy": 7,
                            "buffs": None,
                            "statuses": [],
                        }
                    ],
                },
            }
        ],
    }


def defense_payload(opponent_action):
    payload = base_payload()
    payload["initial"]["opponent_team"][0]["suspected_skills"] = ["防御"]
    payload["turns"][0]["opp_action"] = opponent_action
    payload["turns"][0]["who_first"] = "opp"
    payload["turns"][0]["counter"] = opponent_action["type"] == "skill"
    payload["turns"][0]["speed_inferable"] = False
    payload["turns"][0]["events"] = [
        {
            "type": "damage",
            "source_side": "our",
            "source_slot": 0,
            "target_side": "theirs",
            "target_slot": 0,
            "skill": "气泡",
            "total_damage": 50,
            "hits": 1,
            "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 87},
            "context": {
                "weather": None,
                "our_marks": None,
                "opp_marks": None,
                "our_active": {
                    "slot": 0, "hp": 383, "energy": 10,
                    "buffs": None, "statuses": [],
                },
                "opp_active": {
                    "slot": 0, "hp_percent": 100, "energy": 10,
                    "buffs": None, "statuses": [],
                },
            },
        }
    ]
    payload["turns"][0]["snapshot_after"] = {
        "active_our": 0,
        "active_opp": 0,
        "weather": None,
        "our_marks": None,
        "opp_marks": None,
        "magic_points": {"our": 4, "opp": 4},
        "our_pets": [
            {"hp": 383, "energy": 7, "buffs": None, "statuses": []}
        ],
        "opp_pets": [
            {"hp_percent": 87, "energy": 9, "buffs": None, "statuses": []}
        ],
    }
    return payload


class TestBattleLog(unittest.TestCase):
    def test_valid_log(self):
        result = rb.analyze_battle_log(base_payload())
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["pet"], "龙息帕尔")
        self.assertLess(opponent["builds"]["remaining"], 46320)
        self.assertIn("龙之利爪", opponent["observed_skills"])
        self.assertEqual(result["turns"][0]["speed_inferable"], True)
        self.assertEqual(result["magic_points"], {"our": 4, "opp": 4})
        self.assertEqual(result["initial_snapshot"]["active_our"], 0)
        self.assertEqual(
            result["initial_snapshot"]["our_pets"][0]["hp"], 383
        )

    def test_rain_weather_is_used(self):
        payload = base_payload()
        payload["turns"][0]["opp_action"] = {"type": "charge", "slot": 0}
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = [
            {
                "type": "damage",
                "source_side": "our",
                "source_slot": 0,
                "target_side": "theirs",
                "target_slot": 0,
                "skill": "气泡",
                "total_damage": 341,
                "hits": 1,
                "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 13},
                "context": {
                    "weather": {"type": "雨天", "remaining": 4},
                    "our_marks": None,
                    "opp_marks": None,
                    "our_active": {
                        "slot": 0, "hp": 383, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                    "opp_active": {
                        "slot": 0, "hp_percent": 100, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                },
            }
        ]
        payload["turns"][0]["snapshot_after"]["weather"] = {
            "type": "雨天", "remaining": 3,
        }
        payload["turns"][0]["snapshot_after"]["opp_pets"][0] = {
            "hp_percent": 13, "energy": 10, "buffs": None, "statuses": [],
        }
        result = rb.analyze_battle_log(payload)
        self.assertTrue(result["turns"][0]["events"][0]["matched"])
        self.assertEqual(result["snapshot"]["weather"]["type"], "雨天")

    def test_battle_active_uses_inferred_ranges(self):
        payload = base_payload()
        payload["initial"]["our_team"][0]["skills"] = ["气泡", "防御"]
        payload["active_our_slot"] = 0
        payload["active_opponent_slot"] = 0
        result = rb.analyze_battle_active(payload)
        self.assertIsNotNone(result["active"])
        self.assertEqual(result["active"]["our_slot"], 0)
        self.assertEqual(result["active"]["opponent_slot"], 0)
        self.assertEqual(
            [skill["skill"] for skill in result["active"]["our_skills"]],
            ["气泡", "防御"],
        )
        self.assertFalse(result["active"]["our_skills"][1]["available"])
        self.assertEqual(
            [skill["skill"] for skill in result["active"]["opponent_skills"]],
            ["龙之利爪"],
        )
        self.assertEqual(
            result["opponent_team"][0]["builds"]["remaining"], 366
        )

    def test_missing_context_skips_inference(self):
        payload = base_payload()
        payload["turns"][0]["events"][1]["context"] = None
        result = rb.analyze_battle_log(payload)
        event = result["turns"][0]["events"][1]
        self.assertFalse(event["matched"])
        self.assertIn("缺少伤害发生时的状态", event["message"])

    def test_unmodeled_mark_skips_inference(self):
        payload = base_payload()
        payload["turns"][0]["events"][1]["context"]["our_marks"] = {
            "positive": {"name": "攻击印记", "layers": 1},
            "negative": None,
        }
        result = rb.analyze_battle_log(payload)
        event = result["turns"][0]["events"][1]
        self.assertFalse(event["matched"])
        self.assertIn("攻击印记", event["message"])

    def test_defense_reduction_is_used(self):
        payload = defense_payload({"type": "skill", "slot": 0, "skill": "防御"})
        result = rb.analyze_battle_log(payload)
        event = result["turns"][0]["events"][0]
        self.assertTrue(event["matched"])
        self.assertFalse(result["turns"][0]["speed_inferable"])

    def test_fiber_defense_buff_is_used(self):
        payload = base_payload()
        payload["initial"]["our_team"][0]["skills"] = ["毒沼"]
        payload["initial"]["opponent_team"][0]["suspected_skills"] = ["纤维化"]
        payload["turns"][0]["our_action"] = {
            "type": "skill", "slot": 0, "skill": "毒沼",
        }
        payload["turns"][0]["opp_action"] = {
            "type": "skill", "slot": 0, "skill": "纤维化",
        }
        payload["turns"][0]["who_first"] = "opp"
        payload["turns"][0]["counter"] = True
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = [
            {
                "type": "damage",
                "source_side": "our",
                "source_slot": 0,
                "target_side": "theirs",
                "target_slot": 0,
                "skill": "毒沼",
                "total_damage": 4,
                "hits": 1,
                "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 99},
                "context": {
                    "weather": None,
                    "our_marks": None,
                    "opp_marks": None,
                    "our_active": {
                        "slot": 0, "hp": 383, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                    "opp_active": {
                        "slot": 0, "hp_percent": 100, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                },
            }
        ]
        payload["turns"][0]["snapshot_after"]["our_pets"][0]["energy"] = 8
        payload["turns"][0]["snapshot_after"]["opp_pets"][0] = {
            "hp_percent": 99, "energy": 8, "buffs": None, "statuses": [],
        }
        result = rb.analyze_battle_log(payload)
        self.assertTrue(result["turns"][0]["events"][0]["matched"])

    def test_void_defense_buff_is_used(self):
        payload = base_payload()
        payload["initial"]["opponent_team"][0]["suspected_skills"] = ["虚化"]
        payload["turns"][0]["our_action"] = {
            "type": "skill", "slot": 0, "skill": "气泡",
        }
        payload["turns"][0]["opp_action"] = {
            "type": "skill", "slot": 0, "skill": "虚化",
        }
        payload["turns"][0]["who_first"] = "opp"
        payload["turns"][0]["counter"] = True
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = [
            {
                "type": "damage",
                "source_side": "our",
                "source_slot": 0,
                "target_side": "theirs",
                "target_slot": 0,
                "skill": "气泡",
                "total_damage": 18,
                "hits": 1,
                "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 95},
                "context": {
                    "weather": None,
                    "our_marks": None,
                    "opp_marks": None,
                    "our_active": {
                        "slot": 0, "hp": 383, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                    "opp_active": {
                        "slot": 0, "hp_percent": 100, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                },
            }
        ]
        payload["turns"][0]["snapshot_after"]["opp_pets"][0] = {
            "hp_percent": 95, "energy": 8, "buffs": None, "statuses": [],
        }
        result = rb.analyze_battle_log(payload)
        self.assertTrue(result["turns"][0]["events"][0]["matched"])

    def test_same_damage_without_defense_does_not_match(self):
        payload = defense_payload({"type": "charge", "slot": 0})
        result = rb.analyze_battle_log(payload)
        event = result["turns"][0]["events"][0]
        self.assertFalse(event["matched"])

    def test_speed_constraint_filters_opponent(self):
        payload = base_payload()
        payload["turns"][0]["our_action"] = {"type": "charge", "slot": 0}
        payload["turns"][0]["opp_action"] = {"type": "charge", "slot": 0}
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = []
        payload["turns"][0]["snapshot_after"]["our_pets"][0]["buffs"] = {
            "temporary": {"spe": 5},
            "permanent": None,
        }
        payload["turns"][0]["snapshot_after"]["our_pets"][0]["energy"] = 10
        payload["turns"][0]["snapshot_after"]["opp_pets"][0]["energy"] = 10
        second = copy.deepcopy(payload["turns"][0])
        second["our_action"] = {"type": "skill", "slot": 0, "skill": "气泡"}
        second["opp_action"] = {"type": "skill", "slot": 0, "skill": "龙之利爪"}
        second["who_first"] = "our"
        second["speed_inferable"] = True
        second["snapshot_after"] = copy.deepcopy(second["snapshot_after"])
        second["snapshot_after"]["our_pets"][0]["buffs"] = {
            "temporary": {"spe": 5},
            "permanent": None,
        }
        payload["turns"].append(second)
        result = rb.analyze_battle_log(payload)
        speed = result["opponent_team"][0]["stats"]["spe"]
        self.assertLessEqual(speed["max"], 203)
        self.assertEqual(result["turns"][1]["speed_inferable"], True)

    def test_hp_change_event(self):
        payload = defense_payload({"type": "charge", "slot": 0})
        payload["turns"][0]["events"] = [
            {
                "type": "hp_change",
                "target_side": "theirs",
                "target_slot": 0,
                "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 80},
            }
        ]
        payload["turns"][0]["snapshot_after"]["opp_pets"][0]["hp_percent"] = 80
        result = rb.analyze_battle_log(payload)
        self.assertTrue(result["turns"][0]["events"][0]["matched"])
        self.assertEqual(result["opponent_team"][0]["current_hp_percent"]["min"], 80)

    def test_ko_replacement_and_magic(self):
        payload = base_payload()
        payload["initial"]["opponent_team"].append(
            {"pet": "奇丽花", "energy": 10}
        )
        payload["turns"][0]["opp_action"] = None
        payload["turns"][0]["who_first"] = "our"
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = [
            {
                "type": "damage",
                "source_side": "our",
                "source_slot": 0,
                "target_side": "theirs",
                "target_slot": 0,
                "skill": "气泡",
                "total_damage": 999,
                "hits": 1,
                "hp_after": {"side": "theirs", "slot": 0, "hp_percent": 0},
                "context": {
                    "weather": None,
                    "our_marks": None,
                    "opp_marks": None,
                    "our_active": {
                        "slot": 0, "hp": 383, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                    "opp_active": {
                        "slot": 0, "hp_percent": 100, "energy": 10,
                        "buffs": None, "statuses": [],
                    },
                },
            }
        ]
        payload["turns"][0]["replacements"] = {"our": None, "opp": 1}
        payload["turns"][0]["snapshot_after"] = {
            "active_our": 0,
            "active_opp": 1,
            "weather": None,
            "our_marks": None,
            "opp_marks": None,
            "magic_points": {"our": 4, "opp": 3},
            "our_pets": [
                {"hp": 383, "energy": 7, "buffs": None, "statuses": []}
            ],
            "opp_pets": [
                {"hp_percent": 0, "energy": 10, "buffs": None, "statuses": []},
                {"hp_percent": 100, "energy": 10, "buffs": None, "statuses": []},
            ],
        }
        result = rb.analyze_battle_log(payload)
        self.assertEqual(result["snapshot"]["active_opp"], 1)
        self.assertEqual(result["magic_points"]["opp"], 3)
        self.assertEqual(
            result["turns"][0]["replacements"]["opp"], 1
        )

    def test_magic_mismatch_warns(self):
        payload = base_payload()
        payload["initial"]["opponent_team"].append(
            {"pet": "奇丽花", "energy": 10}
        )
        payload["turns"][0]["opp_action"] = None
        payload["turns"][0]["who_first"] = "our"
        payload["turns"][0]["speed_inferable"] = False
        payload["turns"][0]["events"] = []
        payload["turns"][0]["replacements"] = {"our": None, "opp": 1}
        payload["turns"][0]["snapshot_after"] = {
            "active_our": 0,
            "active_opp": 1,
            "weather": None,
            "our_marks": None,
            "opp_marks": None,
            "magic_points": {"our": 4, "opp": 4},
            "our_pets": [
                {"hp": 383, "energy": 7, "buffs": None, "statuses": []}
            ],
            "opp_pets": [
                {"hp_percent": 0, "energy": 10, "buffs": None, "statuses": []},
                {"hp_percent": 100, "energy": 10, "buffs": None, "statuses": []},
            ],
        }
        result = rb.analyze_battle_log(payload)
        self.assertTrue(any("魔力值" in text for text in result["warnings"]))

    def test_both_switch_uses_pre_switch_speed(self):
        payload = base_payload()
        payload["initial"]["our_team"].append(
            {
                "pet": "水灵",
                "nature": "聪明",
                "talents": {"spa": 10},
                "skills": ["气泡"],
                "energy": 10,
            }
        )
        payload["initial"]["opponent_team"].append(
            {"pet": "奇丽花", "energy": 10}
        )
        first = payload["turns"][0]
        first["our_action"] = {"type": "charge", "slot": 0}
        first["opp_action"] = {"type": "charge", "slot": 0}
        first["speed_inferable"] = False
        first["events"] = []
        first["snapshot_after"] = {
            "active_our": 0,
            "active_opp": 0,
            "weather": None,
            "our_marks": None,
            "opp_marks": None,
            "magic_points": {"our": 4, "opp": 4},
            "our_pets": [
                {
                    "hp": 383,
                    "energy": 10,
                    "buffs": {"temporary": {"spe": 5}, "permanent": None},
                    "statuses": [],
                },
                {"hp": 383, "energy": 10, "buffs": None, "statuses": []},
            ],
            "opp_pets": [
                {"hp_percent": 100, "energy": 10, "buffs": None, "statuses": []},
                {"hp_percent": 100, "energy": 10, "buffs": None, "statuses": []},
            ],
        }
        second = copy.deepcopy(first)
        second["our_action"] = {"type": "switch", "slot": 0, "to_slot": 1}
        second["opp_action"] = {"type": "switch", "slot": 0, "to_slot": 1}
        second["who_first"] = "our"
        second["speed_inferable"] = True
        second["snapshot_after"]["active_our"] = 1
        second["snapshot_after"]["active_opp"] = 1
        payload["turns"].append(second)
        result = rb.analyze_battle_log(payload)
        self.assertEqual(result["turns"][1]["speed_inferable"], True)
        self.assertLessEqual(
            result["opponent_team"][0]["stats"]["spe"]["max"], 203
        )

    def test_bad_version(self):
        payload = base_payload()
        payload["version"] = 99
        with self.assertRaises(rb.BattleLogError):
            rb.analyze_battle_log(payload)

    def test_switch_continuity(self):
        payload = base_payload()
        payload["initial"]["our_team"].append(
            {"pet": "水灵", "nature": "聪明", "talents": {"spa": 10},
             "skills": ["气泡"], "energy": 10}
        )
        payload["turns"][0]["our_action"] = {
            "type": "switch", "slot": 0, "to_slot": 1,
        }
        payload["turns"][0]["snapshot_after"]["active_our"] = 1
        payload["turns"][0]["snapshot_after"]["our_pets"].append(
            {"hp": 383, "energy": 10, "buffs": None, "statuses": []}
        )
        result = rb.analyze_battle_log(payload)
        self.assertEqual(result["snapshot"]["active_our"], 1)

    def test_switch_continuity_error(self):
        payload = base_payload()
        payload["initial"]["our_team"].append(
            {"pet": "水灵", "nature": "聪明", "talents": {"spa": 10},
             "skills": ["气泡"], "energy": 10}
        )
        payload["turns"][0]["our_action"] = {
            "type": "switch", "slot": 0, "to_slot": 1,
        }
        # 故意不把 snapshot_after 的当前出战改成 1
        with self.assertRaises(rb.BattleLogError):
            rb.analyze_battle_log(payload)


class TestSkillRules(unittest.TestCase):
    def test_own_priority_only(self):
        self.assertEqual(rsr.skill_priority("造成物伤，先手+1。"), (1, None))
        self.assertEqual(
            rsr.skill_priority("减伤50%，应对攻击：下一次行动获得先手+1。"),
            (0, None),
        )
        self.assertEqual(
            rsr.skill_priority("敌方先手-1，应对防御：额外使敌方获得双攻-70%。"),
            (0, None),
        )
        self.assertEqual(
            rsr.skill_priority("本技能先手-1，选择：若自己生命低于20%……"),
            (-1, None),
        )

    def test_conditional_priority(self):
        value, note = rsr.skill_priority(
            "造成物伤，位于1号位时，先手+1。传动1。"
        )
        self.assertEqual(value, 0)
        self.assertIn("1号位", note)

    def test_defense_plan(self):
        plan = rsr.defense_damage_plan("防御", "减伤70%，应对攻击。")
        self.assertTrue(plan["supported"])
        self.assertEqual(plan["reduction"], 70)
        variable = rsr.defense_damage_plan(
            "相位移动",
            "减伤50%，本技能位于1号位或3号位时，额外减伤40%，应对攻击，传动1。",
        )
        self.assertFalse(variable["supported"])

    def test_fiber_and_void_pre_damage(self):
        self.assertEqual(
            rsr.defense_pre_damage_layers("纤维化", "物攻"), {"def": 7}
        )
        self.assertEqual(
            rsr.defense_pre_damage_layers("虚化", "魔攻"), {"spd": 7}
        )
        self.assertEqual(rsr.defense_pre_damage_layers("纤维化", "魔攻"), {})


if __name__ == "__main__":
    unittest.main()
