"""下游结构的关键边界，不依赖 OCR 模型或用户截图。"""

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ocr_frame import pet_result, select_number, skill_result, validate_layout


class TestStructuredFrame(unittest.TestCase):
    def test_zero_energy_is_valid_and_ambiguous_numbers_are_rejected(self):
        self.assertEqual(select_number([
            {"text": "D", "confidence": 0.99},
            {"text": "0", "confidence": 0.7},
            {"text": "0", "confidence": 0.6},
        ]), 0)
        self.assertIsNone(select_number([
            {"text": "3", "confidence": 0.95},
            {"text": "8", "confidence": 0.94},
        ]))
        self.assertIsNone(select_number([
            {"text": "星7", "confidence": 0.99},
        ]))

    def test_nickname_does_not_become_database_identity(self):
        pet = pet_result("钥匙扣", 9)
        self.assertIsNone(pet["name"])
        self.assertEqual(pet["display_name"], "钥匙扣")
        self.assertEqual(pet["energy"], 9)
        pet = pet_result("玩家昵称", 0, {"name": "迪莫", "number": "001", "form": ""})
        self.assertEqual(pet["name"], "迪莫")
        self.assertEqual(pet["energy"], 0)

    def test_displayed_power_is_never_filled_from_base_power(self):
        reading = [{"name": "倾泻", "category": "攻击", "base_power": 70,
                    "status": "exact"}]
        result = skill_result(1, reading, 58, 3)
        self.assertEqual((result["power"], result["base_power"]), (58, 70))
        missing = skill_result(1, reading, None, 3)
        self.assertIsNone(missing["power"])
        self.assertEqual(missing["power_status"], "unresolved")

    def test_non_attack_power_is_null_and_missing_slot_is_preserved(self):
        defense = skill_result(2, [{"name": "能量守恒", "category": "防御",
                                   "status": "exact"}], 8, 2)
        self.assertIsNone(defense["power"])
        self.assertEqual(defense["power_status"], "not_applicable")
        missing = skill_result(3, [], 123, None)
        self.assertEqual(missing["slot"], 3)
        self.assertIsNone(missing["name"])
        self.assertIsNone(missing["power"])

    def test_layout_must_match_resolution_and_have_four_unique_slots(self):
        path = Path(__file__).resolve().parents[1] / "configs" / "ocr_reference4.json"
        layout = json.loads(path.read_text())
        validate_layout(layout, (2094, 1179))
        with self.assertRaises(ValueError):
            validate_layout(layout, (1608, 944))
        duplicate = copy.deepcopy(layout)
        duplicate["skills"][1]["slot"] = 1
        with self.assertRaises(ValueError):
            validate_layout(duplicate, (2094, 1179))


if __name__ == "__main__":
    unittest.main()
