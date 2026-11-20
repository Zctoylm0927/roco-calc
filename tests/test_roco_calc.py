#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板值计算的单元测试。

运行方式（项目根目录）:
    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import roco_calc as rc  # noqa: E402


class TestPetLookup(unittest.TestCase):
    def test_find_by_name_and_form(self):
        pet = rc.find_pet("岚鸟", "春天的样子")
        self.assertEqual(pet["hp"], 93)
        self.assertEqual(pet["atk"], 128)
        self.assertEqual(pet["form"], "春天的样子")

    def test_name_with_form_in_parentheses(self):
        pet = rc.find_pet("岚鸟（春天的样子）")
        self.assertEqual(pet["form"], "春天的样子")

    def test_ambiguous_name_requires_form(self):
        with self.assertRaises(rc.AmbiguousPetError) as ctx:
            rc.find_pet("岚鸟")
        self.assertIn("本来的样子", ctx.exception.forms)

    def test_single_base_form_is_chosen(self):
        pet = rc.find_pet("迪莫")
        self.assertEqual(pet["name"], "迪莫")
        self.assertEqual(pet["form"], "")

    def test_missing_pet(self):
        with self.assertRaises(rc.PetNotFoundError):
            rc.find_pet("不存在的精灵")


class TestNatureLookup(unittest.TestCase):
    def test_nature_relations(self):
        nature = rc.get_nature("大胆")
        self.assertEqual(nature["up_key"], "atk")
        self.assertEqual(nature["down_key"], "def")

    def test_neutral_nature(self):
        self.assertIsNone(rc.get_nature("无"))

    def test_missing_nature(self):
        with self.assertRaises(rc.NatureNotFoundError):
            rc.get_nature("不存在的性格")


class TestTalents(unittest.TestCase):
    def test_default_is_all_zero(self):
        talents = rc.normalize_talents()
        self.assertTrue(all(value == 0 for value in talents.values()))

    def test_accepts_chinese_names(self):
        talents = rc.normalize_talents({"物攻": 10, "速度": 3})
        self.assertEqual(talents["atk"], 10)
        self.assertEqual(talents["spe"], 3)

    def test_rejects_more_than_three_nonzero(self):
        with self.assertRaises(rc.TalentError):
            rc.normalize_talents({"atk": 10, "def": 10, "spa": 10, "spe": 10})

    def test_rejects_out_of_range(self):
        with self.assertRaises(rc.TalentError):
            rc.normalize_talents({"atk": 11})

    def test_rejects_unknown_key(self):
        with self.assertRaises(rc.TalentError):
            rc.normalize_talents({"foo": 1})


class TestStatFormula(unittest.TestCase):
    def test_article_attacker_physical_attack(self):
        # 岚鸟 物攻种族 128，天分 10 → 234（公开文章实例）
        self.assertEqual(
            rc.calculate_stat(128, 10, None, "atk", 60),
            234,
        )

    def test_article_defender_physical_defense(self):
        # 奇丽花 物防种族 121，天分 10 → 226（公开文章实例）
        self.assertEqual(
            rc.calculate_stat(121, 10, None, "def", 60),
            226,
        )

    def test_nature_boost(self):
        # 固执 = 物攻↑ / 魔攻↓
        self.assertEqual(rc.calculate_stat(128, 10, "固执", "atk", 60), 271)

    def test_nature_drop(self):
        self.assertEqual(rc.calculate_stat(55, 10, "固执", "spa", 60), 144)

    def test_hp_formula(self):
        self.assertEqual(rc.calculate_stat(112, 10, None, "hp", 60), 411)

    def test_hp_nature_boost(self):
        # 沉默 = 生命↑ / 物攻↓
        self.assertEqual(rc.calculate_stat(112, 10, "沉默", "hp", 60), 473)

    def test_half_to_odd_when_talent_zero(self):
        # 1.1 × 45 = 49.5，整数部分 49 是奇数，半到奇数取 49
        self.assertEqual(rc.calculate_stat(45, 0, None, "atk", 60), 109)
        # 1.1 × 55 = 60.5，整数部分 60 是偶数，半到奇数取 61
        self.assertEqual(rc.calculate_stat(55, 0, None, "atk", 60), 121)

    def test_hp_half_to_odd_when_talent_zero(self):
        # 1.7 × 45 = 76.5，整数部分 76 是偶数 → 77
        self.assertEqual(rc.calculate_stat(45, 0, None, "hp", 60), 247)
        # 1.7 × 75 = 127.5，整数部分 127 是奇数 → 127
        self.assertEqual(rc.calculate_stat(75, 0, None, "hp", 60), 297)

    def test_level_zero_is_treated_as_level_one(self):
        self.assertEqual(
            rc.calculate_stat(100, 0, None, "atk", 0),
            rc.calculate_stat(100, 0, None, "atk", 1),
        )

    def test_panel_has_all_six_stats(self):
        panel = rc.calculate_panel("奇丽花")
        self.assertEqual(set(panel), set(rc.STAT_KEYS))
        self.assertTrue(all(isinstance(value, int) for value in panel.values()))


class TestBuildPanel(unittest.TestCase):
    def test_article_case(self):
        panel = rc.build_panel(
            "岚鸟", form="本来的样子", talents={"atk": 10}, level=60
        )
        self.assertEqual(panel["stats"]["atk"], 234)

        defender = rc.build_panel("奇丽花", talents={"def": 10}, level=60)
        self.assertEqual(defender["stats"]["def"], 226)

    def test_build_panel_context(self):
        panel = rc.build_panel(
            "岚鸟", form="本来的样子", nature="固执", talents={"atk": 10}
        )
        self.assertEqual(panel["nature"]["name"], "固执")
        self.assertEqual(panel["talents"]["atk"], 10)
        self.assertEqual(panel["level"], 60)
        self.assertEqual(panel["stats"]["atk"], 271)


if __name__ == "__main__":
    unittest.main()
