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


class TestSkillLookup(unittest.TestCase):
    def test_find_attack_skill(self):
        skill = rc.find_skill("扇风")
        self.assertEqual(skill["category"], "攻击")
        self.assertEqual(skill["element"], "翼系")
        self.assertEqual(skill["damage_class"], "物攻")
        self.assertEqual(skill["power"], 75)
        self.assertEqual(skill["energy"], 3)

    def test_missing_skill(self):
        with self.assertRaises(rc.SkillNotFoundError):
            rc.find_skill("不存在的技能")


class TestTypeMultiplier(unittest.TestCase):
    def test_single_weakness(self):
        self.assertEqual(rc.type_multiplier("翼系", ["草系"]), 2.0)

    def test_double_weakness_is_three(self):
        self.assertEqual(rc.type_multiplier("火系", ["草系", "冰系"]), 3.0)

    def test_resistance(self):
        self.assertEqual(rc.type_multiplier("火系", ["水系"]), 0.5)
        self.assertEqual(rc.type_multiplier("翼系", ["电系"]), 0.5)

    def test_typeless_and_unlisted(self):
        self.assertEqual(rc.type_multiplier("无系别", ["草系"]), 1.0)
        self.assertEqual(rc.type_multiplier("普通系", ["普通系"]), 1.0)

    def test_dual_type_order_does_not_matter(self):
        self.assertEqual(
            rc.type_multiplier("火系", ["草系", "冰系"]),
            rc.type_multiplier("火系", ["冰系", "草系"]),
        )


class TestDamageFormula(unittest.TestCase):
    def _article_case(self, **overrides):
        options = {
            "attacker_form": "本来的样子",
            "attacker_talents": {"atk": 10},
            "defender_talents": {"def": 10},
            "power": 142.5,
        }
        options.update(overrides)
        return rc.calculate_matchup("岚鸟", "奇丽花", "扇风", **options)

    def test_article_case(self):
        result = self._article_case()
        self.assertEqual(result["attacker_stat"], 234)
        self.assertEqual(result["defender_defense"], 226)
        self.assertEqual(result["effective_power"], 142.5)
        self.assertEqual(result["stab"], 1.25)
        self.assertEqual(result["type_multiplier"], 2.0)
        self.assertEqual(result["display_power"], 356)
        self.assertEqual(result["damage_per_hit"], 332)
        self.assertEqual(result["damage"], 332)
        self.assertFalse(result["is_knockout"])

    def test_uses_skill_power_when_not_overridden(self):
        result = rc.calculate_matchup(
            "岚鸟", "奇丽花", "扇风",
            attacker_form="本来的样子",
            attacker_talents={"atk": 10},
            defender_talents={"def": 10},
        )
        self.assertEqual(result["base_power"], 75)
        self.assertEqual(result["display_power"], 188)
        self.assertEqual(result["damage"], 175)

    def test_stab_is_absent_for_off_type_skill(self):
        result = rc.calculate_matchup(
            "岚鸟", "奇丽花", "抓挠",
            attacker_form="本来的样子",
            attacker_talents={"atk": 10},
            defender_talents={"def": 10},
        )
        self.assertEqual(result["stab"], 1.0)
        self.assertEqual(result["damage"], 32)

    def test_hit_count_multiplies_total_damage(self):
        result = self._article_case(hit_count=2)
        self.assertEqual(result["damage_per_hit"], 332)
        self.assertEqual(result["damage"], 664)
        self.assertTrue(result["is_knockout"])

    def test_final_damage_multiplier(self):
        result = self._article_case(damage_multiplier_percent=50)
        self.assertEqual(result["damage"], 166)

    def test_damage_reduction(self):
        result = self._article_case(damage_reduction_percent=50)
        self.assertEqual(result["damage"], 166)

    def test_attack_stage_modifier(self):
        result = self._article_case(attack_modifier_percent=100)
        self.assertEqual(result["ability_multiplier"], 2.0)
        self.assertEqual(result["display_power"], 713)
        self.assertEqual(result["damage"], 666)

    def test_defense_stage_modifier(self):
        result = self._article_case(defense_modifier_percent=-100)
        self.assertEqual(result["ability_multiplier"], 2.0)
        self.assertEqual(result["damage"], 666)

    def test_power_percent(self):
        result = self._article_case(power_percent=10)
        self.assertEqual(result["effective_power"], 156.75)
        self.assertEqual(result["display_power"], 392)
        self.assertEqual(result["damage"], 366)

    def test_ignore_type_resistance(self):
        options = {
            "attacker_form": "本来的样子",
            "attacker_talents": {"atk": 10},
            "defender_talents": {"hp": 10},
            "power": 100,
        }
        normal = rc.calculate_matchup("岚鸟", "电咩咩", "扇风", **options)
        ignored = rc.calculate_matchup(
            "岚鸟", "电咩咩", "扇风", ignore_type_resistance=True, **options
        )
        self.assertEqual(normal["type_multiplier"], 0.5)
        self.assertEqual(ignored["type_multiplier"], 1.0)
        self.assertGreater(ignored["damage"], normal["damage"])

    def test_status_skill_rejected(self):
        attacker = rc.build_panel("岚鸟", form="本来的样子")
        defender = rc.build_panel("奇丽花")
        skill = rc.find_skill("光合作用")
        with self.assertRaises(rc.NotDamageSkillError):
            rc.calculate_damage(attacker, defender, skill)

    def test_invalid_hit_count(self):
        with self.assertRaises(rc.DamageInputError):
            self._article_case(hit_count=0)

    def test_result_is_json_serializable(self):
        import json
        result = self._article_case()
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
