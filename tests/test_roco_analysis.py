#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""范围推断（对方未知性格/天分）的单元测试。

运行方式（项目根目录）:
    python -m unittest discover -s tests -v
"""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze  # noqa: E402
import roco_analysis as ra  # noqa: E402
import roco_calc as rc  # noqa: E402


def water_vs_paal(observations=None, **extra):
    state = {
        "our_pet": {
            "name": "水灵",
            "nature": "聪明",
            "talents": {"spa": 10},
        },
        "opponent_pet": {"name": "龙息帕尔"},
        "skill": "气泡",
        "observations": observations or [],
    }
    state.update(extra)
    return state


class TestCandidateUniverse(unittest.TestCase):
    def test_total_is_46320(self):
        result = ra.analyze_battle(water_vs_paal())
        builds = result["opponent"]["builds"]
        self.assertEqual(builds["total"], 46320)
        self.assertEqual(builds["remaining"], 46320)

    def test_chinese_name(self):
        result = ra.analyze_battle(
            {
                "our_pet": {
                    "name": "水灵",
                    "nature": "聪明",
                    "talents": {"魔攻": 10},
                },
                "opponent_pet": {"name": "龙息帕尔"},
                "skill": "气泡",
            }
        )
        self.assertEqual(result["damage"]["min"], 140)

    def test_candidate_list_constraints(self):
        candidates = ra.build_candidates("龙息帕尔")
        self.assertEqual(len(candidates), 46320)
        for candidate in candidates:
            talents = candidate["talents"]
            self.assertEqual(len(talents), 6)
            nonzero = [value for value in talents if value]
            self.assertTrue(1 <= len(nonzero) <= 3)
            self.assertTrue(set(nonzero) <= {7, 8, 9, 10})
        natures = {candidate["nature"] for candidate in candidates}
        self.assertEqual(len(natures), 30)

    def test_initial_ranges_and_value_counts(self):
        stats = ra.analyze_battle(water_vs_paal())["opponent"]["stats"]
        expected = {
            "hp": (362, 510),
            "atk": (185, 270),
            "def": (189, 274),
            "spa": (116, 177),
            "spd": (145, 217),
            "spe": (158, 234),
        }
        for key, (low, high) in expected.items():
            self.assertEqual((stats[key]["min"], stats[key]["max"]), (low, high))
            self.assertEqual(len(stats[key]["possible_values"]), 15)

    def test_natures_have_one_up_and_one_down(self):
        natures = rc.load_natures()
        self.assertEqual(len(natures), 30)
        for nature in natures.values():
            self.assertNotEqual(nature["up_key"], nature["down_key"])
            self.assertIn(nature["up_key"], rc.STAT_KEYS)
            self.assertIn(nature["down_key"], rc.STAT_KEYS)


class TestInitialDamage(unittest.TestCase):
    def test_bubble_damage_range(self):
        damage = ra.analyze_battle(water_vs_paal())["damage"]
        self.assertEqual(damage["skill"], "气泡")
        self.assertEqual(damage["defense_key"], "spd")
        self.assertEqual(damage["min"], 140)
        self.assertEqual(damage["max"], 210)
        self.assertEqual(damage["min_case_defense"], 217)
        self.assertEqual(damage["max_case_defense"], 145)
        self.assertEqual(damage["damage_percent_min"], 27.5)
        self.assertEqual(damage["damage_percent_max"], 58.0)
        self.assertEqual(damage["knockout"], "impossible")

    def test_initial_possible_natures(self):
        opponent = ra.analyze_battle(water_vs_paal())["opponent"]
        self.assertEqual(opponent["natures_remaining"], 30)
        self.assertEqual(len(opponent["possible_natures"]), 30)


class TestDamageObservation(unittest.TestCase):
    def test_rain_341_locks_magic_defense(self):
        result = ra.analyze_battle(
            water_vs_paal(
                [{"type": "damage", "damage": 341}], weather="雨天"
            )
        )
        opponent = result["opponent"]
        self.assertEqual(opponent["builds"]["remaining"], 16400)
        self.assertEqual(opponent["natures_remaining"], 20)
        self.assertEqual(opponent["stats"]["spd"]["possible_values"], [156])
        observation = opponent["observations"][0]
        self.assertTrue(observation["matched"])
        self.assertEqual(observation["kept"], 16400)
        self.assertEqual(result["damage"]["min"], 341)

    def test_buff_layers_apply_to_observation(self):
        result = ra.analyze_battle(
            water_vs_paal(
                [
                    {
                        "type": "damage",
                        "damage": 234,
                        "our_buffs": {"spa": 2},
                    }
                ]
            )
        )
        opponent = result["opponent"]
        self.assertEqual(opponent["stats"]["spd"]["possible_values"], [156])
        self.assertEqual(opponent["builds"]["remaining"], 16400)

    def test_starfall_damage_is_included(self):
        result = ra.analyze_battle(
            water_vs_paal(
                [{"type": "damage", "damage": 284, "starfall_layers": 3}]
            )
        )
        opponent = result["opponent"]
        self.assertEqual(opponent["stats"]["spd"]["possible_values"], [156])
        self.assertEqual(opponent["builds"]["remaining"], 16400)

    def test_unmatched_damage_does_not_shrink(self):
        opponent = ra.analyze_battle(
            water_vs_paal([{"type": "damage", "damage": 342}])
        )["opponent"]
        self.assertEqual(opponent["builds"]["remaining"], 46320)
        self.assertEqual(opponent["natures_remaining"], 30)
        self.assertFalse(opponent["observations"][0]["matched"])
        self.assertEqual(len(opponent["warnings"]), 1)
        self.assertIn("对不上", opponent["warnings"][0])


class TestHpPercentObservation(unittest.TestCase):
    def test_195_then_50_percent_locks_hp(self):
        result = ra.analyze_battle(
            water_vs_paal(
                [
                    {
                        "type": "hp_percent",
                        "hp_percent": 50,
                        "total_damage": 195,
                    }
                ]
            )
        )
        opponent = result["opponent"]
        self.assertEqual(opponent["stats"]["hp"]["possible_values"], [391])
        self.assertEqual(opponent["builds"]["remaining"], 16400)
        self.assertEqual(opponent["natures_remaining"], 20)
        self.assertTrue(opponent["observations"][0]["matched"])

    def test_ceil_rounding_cannot_match(self):
        opponent = ra.analyze_battle(
            water_vs_paal(
                [{"type": "hp_percent", "hp_percent": 50, "total_damage": 195}],
                hp_percent_rounding="ceil",
            )
        )["opponent"]
        self.assertEqual(opponent["builds"]["remaining"], 46320)
        self.assertFalse(opponent["observations"][0]["matched"])

    def test_zero_percent_only_keeps_overkill(self):
        opponent = ra.analyze_battle(
            water_vs_paal(
                [{"type": "hp_percent", "hp_percent": 0, "total_damage": 600}]
            )
        )["opponent"]
        self.assertTrue(opponent["observations"][0]["matched"])
        self.assertEqual(opponent["builds"]["remaining"], 46320)


class TestCombinedObservations(unittest.TestCase):
    def test_two_records_apply_global_constraints(self):
        result = ra.analyze_battle(
            water_vs_paal(
                [
                    {"type": "damage", "damage": 341},
                    {
                        "type": "hp_percent",
                        "hp_percent": 50,
                        "total_damage": 195,
                    },
                ],
                weather="雨天",
            )
        )
        opponent = result["opponent"]
        self.assertEqual(opponent["builds"]["remaining"], 4416)
        self.assertEqual(opponent["natures_remaining"], 12)
        self.assertEqual(opponent["stats"]["hp"]["possible_values"], [391])
        self.assertEqual(opponent["stats"]["spd"]["possible_values"], [156])
        self.assertEqual(
            [item["kept"] for item in opponent["observations"]],
            [16400, 4416],
        )

    def test_remaining_natures_avoid_locked_stats(self):
        opponent = ra.analyze_battle(
            water_vs_paal(
                [
                    {"type": "damage", "damage": 341},
                    {
                        "type": "hp_percent",
                        "hp_percent": 50,
                        "total_damage": 195,
                    },
                ],
                weather="雨天",
            )
        )["opponent"]
        natures = rc.load_natures()
        locked = {"hp", "spd"}
        for name in opponent["possible_natures"]:
            self.assertNotIn(natures[name]["up_key"], locked)
            self.assertNotIn(natures[name]["down_key"], locked)


class TestValidation(unittest.TestCase):
    def test_unknown_observation_type(self):
        with self.assertRaises(ra.AnalysisError) as ctx:
            ra.analyze_battle(
                water_vs_paal([{"type": "heal", "hp_percent": 50}])
            )
        self.assertIn("未知的记录类型", str(ctx.exception))

    def test_hp_percent_out_of_range(self):
        with self.assertRaises(ra.AnalysisError):
            ra.analyze_battle(
                water_vs_paal(
                    [
                        {
                            "type": "hp_percent",
                            "hp_percent": 101,
                            "total_damage": 195,
                        }
                    ]
                )
            )

    def test_negative_damage(self):
        with self.assertRaises(ra.AnalysisError):
            ra.analyze_battle(
                water_vs_paal([{"type": "damage", "damage": -1}])
            )

    def test_non_integer_damage(self):
        with self.assertRaises(ra.AnalysisError):
            ra.analyze_battle(
                water_vs_paal([{"type": "damage", "damage": 341.5}])
            )

    def test_opponent_attacker_not_supported(self):
        with self.assertRaises(ra.AnalysisError) as ctx:
            ra.analyze_battle(
                water_vs_paal(
                    [{"type": "damage", "attacker": "theirs", "damage": 341}]
                )
            )
        self.assertIn("第一版", str(ctx.exception))

    def test_invalid_rounding_mode(self):
        with self.assertRaises(ra.AnalysisError):
            ra.analyze_battle(water_vs_paal(hp_percent_rounding="nearest"))

    def test_missing_our_pet_name(self):
        with self.assertRaises(ra.AnalysisError):
            ra.analyze_battle(
                {
                    "our_pet": {},
                    "opponent_pet": {"name": "龙息帕尔"},
                    "skill": "气泡",
                }
            )


class TestCli(unittest.TestCase):
    def test_json_output(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = analyze.main(
                [
                    "--our",
                    "水灵",
                    "--nature",
                    "聪明",
                    "--talent",
                    "魔攻=10",
                    "--opponent",
                    "龙息帕尔",
                    "--skill",
                    "气泡",
                    "--weather",
                    "雨天",
                    "--observe",
                    "341",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["opponent"]["builds"]["remaining"], 16400)
        self.assertEqual(result["opponent"]["stats"]["spd"]["min"], 156)

    def test_hp_record_syntax(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = analyze.main(
                [
                    "--our",
                    "水灵",
                    "--nature",
                    "聪明",
                    "--talent",
                    "魔攻=10",
                    "--opponent",
                    "龙息帕尔",
                    "--skill",
                    "气泡",
                    "--observe",
                    "hp:50:195",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["opponent"]["stats"]["hp"]["min"], 391)


if __name__ == "__main__":
    unittest.main()
