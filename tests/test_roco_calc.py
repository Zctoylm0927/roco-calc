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

    def test_parentheses_and_form_argument_together(self):
        pet = rc.find_pet("岚鸟（春天的样子）", "春天的样子")
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
        talents = rc.normalize_talents({"物攻": 10, "速度": 7})
        self.assertEqual(talents["atk"], 10)
        self.assertEqual(talents["spe"], 7)

    def test_rejects_more_than_three_nonzero(self):
        with self.assertRaises(rc.TalentError):
            rc.normalize_talents({"atk": 10, "def": 10, "spa": 10, "spe": 10})

    def test_rejects_out_of_range(self):
        with self.assertRaises(rc.TalentError):
            rc.normalize_talents({"atk": 11})

    def test_only_zero_and_seven_to_ten_are_valid(self):
        for value in (0, 7, 8, 9, 10):
            self.assertEqual(
                rc.normalize_talents({"atk": value})["atk"], value
            )
        for value in (1, 2, 3, 4, 5, 6, 11):
            with self.assertRaises(rc.TalentError):
                rc.normalize_talents({"atk": value})

    def test_stat_formula_rejects_impossible_talent(self):
        with self.assertRaises(rc.TalentError):
            rc.calculate_stat(100, 3, None, "atk", 60)

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
        self.assertEqual(result["display_power_raw"], 712.5)
        # 伤害使用未取整的 712.5；若用取整后的 713 会高 1 点。
        self.assertEqual(result["damage"], 665)

    def test_defense_stage_modifier(self):
        result = self._article_case(defense_modifier_percent=-100)
        self.assertEqual(result["ability_multiplier"], 2.0)
        self.assertEqual(result["display_power_raw"], 712.5)
        self.assertEqual(result["damage"], 665)

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


class TestWeatherDamage(unittest.TestCase):
    """游戏内实测：水灵（聪明、魔攻天分 10）打龙息帕尔。"""

    def _water_case(self, skill, **overrides):
        options = {
            "attacker_nature": "聪明",
            "attacker_talents": {"spa": 10},
        }
        options.update(overrides)
        return rc.calculate_matchup("水灵", "龙息帕尔", skill, **options)

    def test_bubble_without_rain(self):
        result = self._water_case("气泡")
        self.assertEqual(result["attacker_stat"], 270)
        self.assertEqual(result["defender_defense"], 156)
        self.assertEqual(result["display_power"], 125)
        self.assertEqual(result["display_power_raw"], 125.0)
        self.assertEqual(result["damage"], 195)

    def test_bubble_with_rain(self):
        result = self._water_case("气泡", weather="雨天")
        self.assertEqual(result["base_power"], 100)
        self.assertEqual(result["weather_base_power"], 175)
        self.assertEqual(result["effective_power"], 175)
        self.assertEqual(result["display_power"], 219)
        self.assertAlmostEqual(result["display_power_raw"], 218.75)
        self.assertEqual(result["damage"], 341)

    def test_water_cannon_without_rain_keeps_fractional_power(self):
        result = self._water_case("水炮")
        self.assertEqual(result["display_power"], 138)
        self.assertEqual(result["display_power_raw"], 137.5)
        self.assertEqual(result["damage"], 214)

    def test_water_cannon_with_rain(self):
        result = self._water_case("水炮", weather="雨天")
        self.assertEqual(result["base_power"], 110)
        self.assertEqual(result["weather_base_power"], 192)
        self.assertEqual(result["effective_power"], 192)
        self.assertEqual(result["display_power"], 240)
        self.assertEqual(result["display_power_raw"], 240.0)
        self.assertEqual(result["damage"], 374)

    def test_non_water_skill_ignores_rain(self):
        result = rc.calculate_matchup(
            "岚鸟", "奇丽花", "扇风",
            attacker_form="本来的样子",
            attacker_talents={"atk": 10},
            defender_talents={"def": 10},
            power=142.5,
            weather="雨天",
        )
        self.assertEqual(result["weather_power_multiplier"], 1.0)
        self.assertEqual(result["damage"], 332)

    def test_other_weather_does_not_change_damage(self):
        result = self._water_case("气泡", weather="沙暴")
        self.assertEqual(result["weather_power_multiplier"], 1.0)
        self.assertEqual(result["damage"], 195)


class TestBuffLayers(unittest.TestCase):
    """增减益按层输入：四维每层 10 个百分点，速度每层 +10 点。"""

    def _water_case(self, skill="气泡", **overrides):
        options = {
            "attacker_nature": "聪明",
            "attacker_talents": {"spa": 10},
        }
        options.update(overrides)
        return rc.calculate_matchup("水灵", "龙息帕尔", skill, **options)

    def test_default_is_all_zero(self):
        buffs = rc.normalize_buffs()
        self.assertEqual(set(buffs), set(rc.BUFF_KEYS))
        self.assertTrue(all(value == 0 for value in buffs.values()))

    def test_accepts_chinese_names_and_keys(self):
        buffs = rc.normalize_buffs({"魔攻": 2, "spe": -1})
        self.assertEqual(buffs["spa"], 2)
        self.assertEqual(buffs["spe"], -1)

    def test_rejects_hp(self):
        with self.assertRaises(rc.BuffError):
            rc.normalize_buffs({"生命": 1})

    def test_rejects_non_integer_and_out_of_range(self):
        with self.assertRaises(rc.BuffError):
            rc.normalize_buffs({"魔攻": 1.5})
        with self.assertRaises(rc.BuffError):
            rc.normalize_buffs({"魔攻": 100})

    def test_magic_attack_buff(self):
        result = self._water_case(attacker_buffs={"魔攻": 2})
        self.assertEqual(result["buff_attack_percent"], 20)
        self.assertEqual(result["ability_multiplier"], 1.2)
        self.assertEqual(result["display_power"], 150)
        self.assertEqual(result["damage"], 234)

    def test_magic_attack_and_defense_drop(self):
        result = self._water_case(
            attacker_buffs={"魔攻": 2}, defender_buffs={"魔防": -1}
        )
        self.assertEqual(result["buff_defense_percent"], -10)
        self.assertEqual(result["ability_multiplier"], 1.3)
        self.assertEqual(result["display_power_raw"], 162.5)
        self.assertEqual(result["damage"], 253)

    def test_off_channel_buffs_do_not_affect_damage(self):
        result = self._water_case(
            attacker_buffs={"物攻": 2}, defender_buffs={"物防": -1}
        )
        self.assertEqual(result["ability_multiplier"], 1.0)
        self.assertEqual(result["damage"], 195)

    def test_speed_layers_only_change_speed(self):
        result = self._water_case(attacker_buffs={"速度": 2})
        self.assertEqual(result["attacker_speed_after_buffs"], 173)
        self.assertEqual(result["ability_multiplier"], 1.0)
        self.assertEqual(result["damage"], 195)

    def test_layers_add_to_explicit_modifiers(self):
        result = self._water_case(
            attacker_buffs={"魔攻": 1}, attack_modifier_percent=10
        )
        self.assertEqual(result["total_attack_modifier_percent"], 20)
        self.assertEqual(result["damage"], 234)

    def test_buffs_do_not_change_rain(self):
        result = self._water_case(
            attacker_buffs={"魔攻": 2}, weather="雨天"
        )
        self.assertEqual(result["weather_base_power"], 175)
        self.assertEqual(result["display_power_raw"], 262.5)
        self.assertEqual(result["damage"], 410)


class TestStarfall(unittest.TestCase):
    """星陨印记：非幻系攻击技能命中带印记的受击方时触发一次，消耗全部层数。"""

    def _water_case(self, skill="气泡", **overrides):
        options = {
            "attacker_nature": "聪明",
            "attacker_talents": {"spa": 10},
        }
        options.update(overrides)
        return rc.calculate_matchup("水灵", "龙息帕尔", skill, **options)

    def test_base_power_table(self):
        expected = {0: 0, 1: 1, 2: 28, 3: 57, 5: 121, 10: 316}
        for layers, power in expected.items():
            self.assertEqual(rc.starfall_base_power(layers), power)

    def test_zero_layers_does_not_trigger(self):
        result = self._water_case(starfall_layers=0)
        self.assertFalse(result["starfall"]["triggered"])
        self.assertEqual(result["starfall_damage"], 0)
        self.assertEqual(result["total_damage"], result["damage"])

    def test_magic_channel_triggers_and_consumes_layers(self):
        result = self._water_case(starfall_layers=3)
        starfall = result["starfall"]
        self.assertTrue(starfall["triggered"])
        self.assertEqual(starfall["base_power"], 57)
        self.assertEqual(starfall["type_multiplier"], 1.0)
        self.assertEqual(starfall["display_power"], 57)
        self.assertEqual(starfall["ability_power"], 57)
        self.assertEqual(starfall["damage"], 89)
        self.assertEqual(starfall["layers_consumed"], 3)
        self.assertEqual(starfall["layers_after"], 0)
        self.assertEqual(result["damage"], 195)
        self.assertEqual(result["total_damage"], 284)

    def test_physical_channel_uses_attack_and_defense(self):
        result = rc.calculate_matchup(
            "岚鸟", "奇丽花", "扇风",
            attacker_form="本来的样子",
            attacker_talents={"atk": 10},
            defender_talents={"def": 10},
            power=142.5,
            starfall_layers=3,
        )
        self.assertEqual(result["attack_key"], "atk")
        self.assertEqual(result["damage"], 332)
        self.assertEqual(result["starfall_damage"], 53)
        self.assertEqual(result["total_damage"], 385)

    def test_illusion_skill_does_not_trigger(self):
        result = self._water_case(skill="坍缩", starfall_layers=3)
        self.assertFalse(result["starfall"]["triggered"])
        self.assertEqual(result["starfall"]["layers_after"], 3)
        self.assertEqual(result["starfall_damage"], 0)
        self.assertEqual(result["total_damage"], 132)

    def test_buff_layers_apply_to_starfall(self):
        result = self._water_case(
            starfall_layers=3, attacker_buffs={"魔攻": 2}
        )
        self.assertEqual(result["ability_multiplier"], 1.2)
        self.assertEqual(result["starfall"]["display_power"], 57)
        self.assertEqual(result["starfall"]["ability_power"], 68)
        self.assertEqual(result["starfall_damage"], 106)
        self.assertEqual(result["total_damage"], 340)

    def test_rounding_difference_example(self):
        # 迪莫是光系，幻系克制 ×0.5：57 × 0.5 = 28.5。
        # tzrain 先四舍五入成 29，额外伤害 40；
        # 若像普通技能一样保留 28.5，额外伤害会是 39（总伤害 213）。
        result = rc.calculate_matchup(
            "水灵", "迪莫", "气泡",
            attacker_nature="聪明",
            attacker_talents={"spa": 10},
            starfall_layers=3,
        )
        self.assertEqual(result["starfall"]["display_power"], 29)
        self.assertEqual(result["starfall_damage"], 40)
        self.assertEqual(result["total_damage"], 214)

    def test_hit_count_does_not_multiply_starfall(self):
        result = self._water_case(starfall_layers=3, hit_count=2)
        self.assertEqual(result["damage"], 390)
        self.assertEqual(result["starfall_damage"], 89)
        self.assertEqual(result["total_damage"], 479)

    def test_final_multiplier_applies_to_starfall(self):
        result = self._water_case(
            starfall_layers=3, damage_multiplier_percent=50
        )
        self.assertEqual(result["damage"], 97)
        self.assertEqual(result["starfall_damage"], 44)
        self.assertEqual(result["total_damage"], 141)

    def test_layer_validation(self):
        for value in (-1, 100, 1.5):
            with self.assertRaises(rc.DamageInputError):
                self._water_case(starfall_layers=value)


class TestCli(unittest.TestCase):
    def test_parse_buffs(self):
        import calc
        self.assertEqual(
            calc.parse_buffs("魔攻=2,速度=-1"),
            {"魔攻": 2, "速度": -1},
        )

    def test_format_result_with_buffs(self):
        import calc
        result = rc.calculate_matchup(
            "水灵", "龙息帕尔", "气泡",
            attacker_nature="聪明",
            attacker_talents={"spa": 10},
            attacker_buffs={"魔攻": 2},
        )
        text = calc.format_result(result)
        self.assertIn("增减益：魔攻 +2 层（+20 个百分点）", text)
        self.assertIn("攻防乘区：×1.2", text)
        self.assertIn("总伤害：234", text)

    def test_format_result_with_starfall(self):
        import calc
        result = rc.calculate_matchup(
            "水灵", "龙息帕尔", "气泡",
            attacker_nature="聪明",
            attacker_talents={"spa": 10},
            starfall_layers=3,
        )
        text = calc.format_result(result)
        self.assertIn("星陨印记：3 层（触发，消耗全部层数）", text)
        self.assertIn("基础威力：57（3² + 24×3 − 24）", text)
        self.assertIn("星陨额外伤害：89", text)
        self.assertIn("总伤害：284", text)

    def test_parse_talents(self):
        import calc
        self.assertEqual(
            calc.parse_talents("物攻=10,速度=7"),
            {"物攻": 10, "速度": 7},
        )

    def test_format_result(self):
        import calc
        result = rc.calculate_matchup(
            "岚鸟", "奇丽花", "扇风",
            attacker_form="本来的样子",
            attacker_talents={"atk": 10},
            defender_talents={"def": 10},
            power=142.5,
        )
        text = calc.format_result(result)
        self.assertIn("显示威力：356", text)
        self.assertIn("总伤害：332", text)
        self.assertIn("不能击倒", text)

    def test_format_result_with_rain(self):
        import calc
        result = rc.calculate_matchup(
            "水灵", "龙息帕尔", "水炮",
            attacker_nature="聪明",
            attacker_talents={"spa": 10},
            weather="雨天",
        )
        text = calc.format_result(result)
        self.assertIn("天气：雨天", text)
        self.assertIn("天气修正后基础威力：192", text)
        self.assertIn("显示威力：240", text)
        self.assertIn("总伤害：374", text)


if __name__ == "__main__":
    unittest.main()
