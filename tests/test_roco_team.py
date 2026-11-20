#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""6 对 6 队伍范围推断的单元测试。

运行方式（项目根目录）:
    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import roco_team as rt  # noqa: E402


OUR_WATER = {
    "pet": "水灵",
    "nature": "聪明",
    "talents": {"spa": 10},
    "skills": ["气泡", "水炮", "天洪", "水弹枪"],
    "current_hp": 306,
}

OPPONENT_PAL = {
    "pet": "龙息帕尔",
    "skills": ["龙之利爪", "升龙咆哮"],
}


def make_state(records=None, our_team=None, opponent_team=None):
    return {
        "level": 60,
        "our_team": [OUR_WATER] if our_team is None else our_team,
        "opponent_team": (
            [OPPONENT_PAL] if opponent_team is None else opponent_team
        ),
        "active_our_slot": 0,
        "active_opponent_slot": 0,
        "records": records or [],
    }


def damage_record(
    skill="气泡",
    damage=195,
    hp_percent=None,
    remaining_hp=None,
    attacker_side="our",
    defender_side="theirs",
    attacker_slot=0,
    defender_slot=0,
):
    record = {
        "type": "damage",
        "attacker_side": attacker_side,
        "attacker_slot": attacker_slot,
        "defender_side": defender_side,
        "defender_slot": defender_slot,
        "skill": skill,
        "damage": damage,
    }
    if hp_percent is not None:
        record["hp_percent"] = hp_percent
    if remaining_hp is not None:
        record["remaining_hp"] = remaining_hp
    return record


class TestTeamSetup(unittest.TestCase):
    def test_empty_slots_are_padded_to_six(self):
        result = rt.analyze_team(make_state())
        self.assertEqual(len(result["our_team"]), 6)
        self.assertEqual(len(result["opponent_team"]), 6)
        self.assertTrue(result["our_team"][0]["configured"])
        self.assertTrue(result["opponent_team"][0]["configured"])
        for index in range(1, 6):
            self.assertFalse(result["our_team"][index]["configured"])
            self.assertFalse(result["opponent_team"][index]["configured"])

    def test_our_five_skills_are_rejected(self):
        our = dict(OUR_WATER)
        our["skills"] = ["气泡", "水炮", "天洪", "水弹枪", "涌泉"]
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(our_team=[our]))

    def test_opponent_can_have_more_than_four_skills(self):
        opponent = {
            "pet": "龙息帕尔",
            "skills": [
                "龙之利爪", "升龙咆哮", "龙吼", "吹炎", "隼鳞", "俯冲猛击",
            ],
        }
        result = rt.analyze_team(make_state(opponent_team=[opponent]))
        self.assertEqual(len(result["active"]["opponent_skills"]), 6)

    def test_status_skill_is_listed_but_not_computable(self):
        our = dict(OUR_WATER)
        our["skills"] = ["光合作用"]
        result = rt.analyze_team(make_state(our_team=[our]))
        skill = result["active"]["our_skills"][0]
        self.assertFalse(skill["available"])
        self.assertIn("不造成直接伤害", skill["reason"])

    def test_active_is_none_when_a_slot_is_empty(self):
        state = make_state()
        state["opponent_team"] = []
        result = rt.analyze_team(state)
        self.assertIsNone(result["active"])

    def test_our_hp_is_an_exact_number_and_has_no_percentage(self):
        result = rt.analyze_team(make_state())
        our = result["our_team"][0]
        self.assertEqual(our["current_hp"], {"min": 306, "max": 306})
        self.assertNotIn("current_hp_percent", our)
        self.assertNotIn("hp_percent", our)
        for skill in result["active"]["opponent_skills"]:
            self.assertIn("our_remaining_hp", skill)
            self.assertNotIn("our_remaining_hp_percent", skill)

    def test_opponent_slots_are_independent(self):
        opponent_team = [
            {"pet": "龙息帕尔"},
            {"pet": "龙息帕尔"},
        ]
        result = rt.analyze_team(make_state(
            records=[damage_record(hp_percent=50)],
            opponent_team=opponent_team,
        ))
        self.assertEqual(
            result["opponent_team"][0]["builds"]["remaining"], 4416
        )
        self.assertEqual(
            result["opponent_team"][1]["builds"]["remaining"], 46320
        )


class TestDamageRecords(unittest.TestCase):
    def test_our_hit_with_remaining_percent(self):
        result = rt.analyze_team(make_state(
            records=[damage_record(damage=195, hp_percent=50)]
        ))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 4416)
        self.assertEqual(opponent["natures_remaining"], 12)
        self.assertEqual(opponent["stats"]["hp"]["min"], 391)
        self.assertEqual(opponent["stats"]["hp"]["max"], 391)
        self.assertEqual(opponent["stats"]["spd"]["min"], 156)
        self.assertEqual(opponent["stats"]["spd"]["max"], 156)
        self.assertEqual(opponent["current_hp"], {"min": 196, "max": 196})
        self.assertEqual(opponent["current_hp_percent"], {"min": 50, "max": 50})
        self.assertTrue(result["records"][0]["matched"])
        self.assertEqual(result["records"][0]["kept"], 4416)

    def test_our_hit_without_percent_only_filters_defense(self):
        result = rt.analyze_team(make_state(
            records=[damage_record(damage=195)]
        ))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 16400)
        self.assertEqual(opponent["stats"]["spd"]["min"], 156)
        self.assertEqual(opponent["stats"]["spd"]["max"], 156)
        self.assertEqual(opponent["stats"]["hp"]["min"], 362)
        self.assertEqual(opponent["stats"]["hp"]["max"], 510)
        self.assertEqual(opponent["current_hp"]["min"], 167)
        self.assertEqual(opponent["current_hp"]["max"], 315)

    def test_opponent_hit_filters_attack_and_updates_our_hp(self):
        result = rt.analyze_team(make_state(records=[
            damage_record(
                skill="龙之利爪",
                damage=160,
                remaining_hp=146,
                attacker_side="theirs",
                defender_side="our",
            )
        ]))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["stats"]["atk"]["min"], 223)
        self.assertEqual(opponent["stats"]["atk"]["max"], 223)
        self.assertEqual(opponent["builds"]["remaining"], 3620)
        self.assertEqual(result["our_team"][0]["current_hp"], {
            "min": 146, "max": 146,
        })
        self.assertTrue(result["records"][0]["matched"])

    def test_observed_opponent_skill_is_added_to_its_skill_list(self):
        opponent = {"pet": "龙息帕尔"}
        result = rt.analyze_team(make_state(
            records=[damage_record(
                skill="龙之利爪",
                damage=160,
                remaining_hp=146,
                attacker_side="theirs",
                defender_side="our",
            )],
            opponent_team=[opponent],
        ))
        self.assertEqual(
            result["opponent_team"][0]["observed_skills"], ["龙之利爪"]
        )
        names = [
            skill["skill"] for skill in result["active"]["opponent_skills"]
        ]
        self.assertEqual(names, ["龙之利爪"])

    def test_unmatched_damage_keeps_the_previous_range(self):
        result = rt.analyze_team(make_state(
            records=[damage_record(damage=999)]
        ))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 46320)
        self.assertFalse(result["records"][0]["matched"])
        self.assertTrue(result["warnings"])
        self.assertIn("没有对上", result["warnings"][0])

    def test_attack_and_defense_must_be_different_sides(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[
                damage_record(
                    attacker_side="our", defender_side="our"
                )
            ]))

    def test_our_hp_mismatch_gives_a_warning_but_uses_the_recorded_value(self):
        result = rt.analyze_team(make_state(records=[
            damage_record(
                skill="龙之利爪",
                damage=160,
                remaining_hp=100,
                attacker_side="theirs",
                defender_side="our",
            )
        ]))
        self.assertEqual(result["our_team"][0]["current_hp"], {
            "min": 100, "max": 100,
        })
        self.assertTrue(result["records"][0]["matched"])
        self.assertTrue(any("146" in text for text in result["warnings"]))

    def test_our_hp_percent_is_rejected(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[
                damage_record(
                    skill="龙之利爪",
                    damage=160,
                    hp_percent=38,
                    attacker_side="theirs",
                    defender_side="our",
                )
            ]))

    def test_opponent_remaining_hp_is_rejected(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[
                damage_record(damage=195, remaining_hp=196)
            ]))

    def test_rain_changes_damage(self):
        state = make_state()
        state["weather"] = "雨天"
        result = rt.analyze_team(state)
        bubble = result["active"]["our_skills"][0]
        self.assertEqual(bubble["damage"], {"min": 245, "max": 367})

    def test_record_can_snapshot_weather(self):
        state = make_state(records=[{
            **damage_record(damage=341),
            "weather": "雨天",
        }])
        result = rt.analyze_team(state)
        opponent = result["opponent_team"][0]
        self.assertTrue(result["records"][0]["matched"])
        self.assertEqual(opponent["stats"]["spd"]["min"], 156)
        self.assertEqual(opponent["stats"]["spd"]["max"], 156)
        self.assertEqual(opponent["builds"]["remaining"], 16400)


class TestHpChanges(unittest.TestCase):
    def test_reset_without_delta_does_not_filter_builds(self):
        result = rt.analyze_team(make_state(records=[{
            "type": "hp_change",
            "side": "theirs",
            "slot": 0,
            "hp_percent": 50,
        }]))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 46320)
        self.assertEqual(opponent["current_hp_percent"], {
            "min": 50, "max": 50,
        })
        self.assertIn(
            "没有使用实际变化量", result["records"][0]["message"]
        )

    def test_reset_with_delta_narrows_max_hp(self):
        result = rt.analyze_team(make_state(records=[{
            "type": "hp_change",
            "side": "theirs",
            "slot": 0,
            "hp_percent": 50,
            "hp_delta": -195,
        }]))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 16400)
        self.assertEqual(opponent["natures_remaining"], 20)
        self.assertEqual(opponent["stats"]["hp"]["min"], 391)
        self.assertEqual(opponent["stats"]["hp"]["max"], 391)
        self.assertEqual(opponent["current_hp"], {"min": 196, "max": 196})

    def test_heal_after_damage_locks_current_hp(self):
        result = rt.analyze_team(make_state(records=[
            damage_record(damage=195, hp_percent=50),
            {
                "type": "hp_change",
                "side": "theirs",
                "slot": 0,
                "hp_percent": 80,
                "hp_delta": 116,
            },
        ]))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 4416)
        self.assertEqual(opponent["current_hp"], {"min": 312, "max": 312})
        self.assertEqual(opponent["current_hp_percent"], {
            "min": 80, "max": 80,
        })

    def test_impossible_heal_from_full_is_skipped(self):
        result = rt.analyze_team(make_state(records=[{
            "type": "hp_change",
            "side": "theirs",
            "slot": 0,
            "hp_percent": 100,
            "hp_delta": 100,
        }]))
        opponent = result["opponent_team"][0]
        self.assertEqual(opponent["builds"]["remaining"], 46320)
        self.assertFalse(result["records"][0]["matched"])
        self.assertTrue(result["warnings"])

    def test_our_hp_change_uses_an_exact_number(self):
        result = rt.analyze_team(make_state(records=[{
            "type": "hp_change",
            "side": "our",
            "slot": 0,
            "hp": 200,
        }]))
        self.assertEqual(result["our_team"][0]["current_hp"], {
            "min": 200, "max": 200,
        })
        self.assertNotIn(
            "current_hp_percent", result["our_team"][0]
        )

    def test_our_hp_change_rejects_percentage(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[{
                "type": "hp_change",
                "side": "our",
                "slot": 0,
                "hp_percent": 50,
            }]))


class TestSkillRanges(unittest.TestCase):
    def test_initial_our_skill_damage_range(self):
        result = rt.analyze_team(make_state())
        bubble = result["active"]["our_skills"][0]
        self.assertEqual(bubble["skill"], "气泡")
        self.assertEqual(bubble["damage"], {"min": 140, "max": 210})
        self.assertIn("remaining_hp_percent", bubble)

    def test_opponent_skill_uses_exact_our_hp(self):
        result = rt.analyze_team(make_state())
        claw = result["active"]["opponent_skills"][0]
        self.assertEqual(claw["skill"], "龙之利爪")
        self.assertEqual(claw["damage"], {"min": 133, "max": 194})
        self.assertEqual(claw["our_remaining_hp"], {
            "min": 112, "max": 173,
        })
        self.assertNotIn("our_remaining_hp_percent", claw)

    def test_our_skill_after_records(self):
        result = rt.analyze_team(make_state(records=[
            damage_record(damage=195, hp_percent=50),
            {
                "type": "hp_change",
                "side": "theirs",
                "slot": 0,
                "hp_percent": 80,
                "hp_delta": 116,
            },
        ]))
        bubble = result["active"]["our_skills"][0]
        self.assertEqual(bubble["damage"], {"min": 195, "max": 195})
        self.assertEqual(bubble["remaining_hp_percent"], {
            "min": 29.9, "max": 29.9,
        })
        self.assertEqual(bubble["knockout"], "impossible")

    def test_opponent_hit_after_record_uses_new_our_hp(self):
        result = rt.analyze_team(make_state(records=[
            damage_record(
                skill="龙之利爪",
                damage=160,
                remaining_hp=146,
                attacker_side="theirs",
                defender_side="our",
            )
        ]))
        claw = result["active"]["opponent_skills"][0]
        self.assertEqual(claw["damage"], {"min": 160, "max": 160})
        self.assertEqual(claw["our_remaining_hp"], {"min": 0, "max": 0})
        self.assertEqual(claw["knockout"], "certain")


class TestValidation(unittest.TestCase):
    def test_invalid_slot_index(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[
                damage_record(attacker_slot=9)
            ]))

    def test_invalid_side_name(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=[
                damage_record(attacker_side="unknown")
            ]))

    def test_too_many_team_slots(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(
                opponent_team=[{"pet": "龙息帕尔"}] * 7
            ))

    def test_our_hp_cannot_exceed_max_hp(self):
        our = dict(OUR_WATER)
        our["current_hp"] = 999
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(our_team=[our]))

    def test_record_must_be_a_dict(self):
        with self.assertRaises(rt.TeamAnalysisError):
            rt.analyze_team(make_state(records=["不是字典"]))


if __name__ == "__main__":
    unittest.main()
