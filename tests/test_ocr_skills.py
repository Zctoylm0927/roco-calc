"""技能池校对的边界：歧义不强选，高置信度错误不静默覆盖。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr_skills import load_skill_pool, match_skill


class TestSkillPoolMatching(unittest.TestCase):
    def test_pool_contains_non_attack_skills(self):
        pool = load_skill_pool("花衣蝶")
        self.assertEqual(pool["虫结阵"]["category"], "防御")
        self.assertEqual(pool["假寐"]["category"], "状态")
        self.assertNotIn("假冒", pool)
        self.assertEqual(pool["飞断"]["base_power"], 20)

    def test_pet_pool_resolves_ambiguous_global_reading(self):
        global_pool = {"假寐": {}, "假冒": {}}
        ambiguous = match_skill("假雅", 0.6, global_pool)
        self.assertEqual(ambiguous["status"], "unresolved")
        self.assertIsNone(ambiguous["name"])
        corrected = match_skill("假雅", 0.6, load_skill_pool("花衣蝶"))
        self.assertEqual(corrected["name"], "假寐")
        self.assertEqual(corrected["status"], "corrected")

    def test_unreliable_or_high_confidence_unknown_is_not_replaced(self):
        pool = {"虫结阵": {}}
        for text, score in [("虫结车", 0.99), ("虫结车", 0.2),
                            ("虫经车", 0.7), ("虫", 0.7), ("虫结阵", 0.2)]:
            with self.subTest(text=text, score=score):
                self.assertIsNone(match_skill(text, score, pool)["name"])

    def test_exact_name_is_preserved(self):
        result = match_skill("能量守恒", 0.99, {"能量守恒": {}})
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["name"], "能量守恒")


if __name__ == "__main__":
    unittest.main()
