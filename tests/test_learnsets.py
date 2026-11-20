#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可学习技能表的单元测试。

运行方式（项目根目录）:
    python -m unittest discover -s tests -v
"""

import csv
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import crawl_learnsets as cl  # noqa: E402


SYNTHETIC_LEARNSETS = """
return {
  learnset_a = {
    native_skills = {{level=1, skill="skill_native", stage=1}, {level=12, skill="skill_shared", stage=1}},
    blood_skills = {{blood="水", level=15, skill="skill_blood"}},
    skill_stones = {"skill_shared", "skill_stone", "skill_missing"},
    feature_skill = "skill_feature"
  }
}
"""


def make_skill(skill_id, name, category="攻击", damage_class="魔攻", power="60"):
    return {
        "skill_id": skill_id,
        "name": name,
        "category": category,
        "element": "水系",
        "damage_class": damage_class,
        "power": power,
    }


class TestParsing(unittest.TestCase):
    def test_parse_learnsets(self):
        learnsets = cl.parse_learnsets(SYNTHETIC_LEARNSETS)
        self.assertEqual(set(learnsets), {"learnset_a"})
        self.assertEqual(len(learnsets["learnset_a"]["native_skills"]), 2)
        self.assertEqual(learnsets["learnset_a"]["feature_skill"], "skill_feature")

    def test_parse_catalog(self):
        catalog = cl.parse_catalog(
            'return {pet_a={id="pet_a", number="010", name="水灵", '
            'stage=3, learnset_id="learnset_a"}}'
        )
        self.assertEqual(catalog["pet_a"]["number"], "010")
        self.assertEqual(catalog["pet_a"]["form"], "")
        self.assertEqual(catalog["pet_a"]["stage"], "3")
        self.assertEqual(catalog["pet_a"]["learnset_id"], "learnset_a")


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "pet_a": {
                "id": "pet_a", "number": "010", "name": "水灵",
                "form": "本来的样子", "stage": "3", "learnset_id": "ls_a",
            },
            "pet_b": {
                "id": "pet_b", "number": "010", "name": "水灵",
                "form": "另一个样子", "stage": "3", "learnset_id": "ls_b",
            },
        }
        self.indexes = cl.build_indexes(self.catalog)

    def test_exact_match(self):
        row = {"number": "010", "name": "水灵", "form": "本来的样子", "stage": "3"}
        entry, kind = cl.match_pet(row, self.indexes)
        self.assertEqual(entry["id"], "pet_a")
        self.assertEqual(kind, "exact")

    def test_same_learnset_fuzzy_match(self):
        catalog = {
            "pet_a": {
                "id": "pet_a", "number": "010", "name": "水灵",
                "form": "本来的样子", "stage": "3", "learnset_id": "ls_a",
            },
            "pet_b": {
                "id": "pet_b", "number": "010", "name": "水灵",
                "form": "旧形态", "stage": "3", "learnset_id": "ls_a",
            },
        }
        indexes = cl.build_indexes(catalog)
        row = {"number": "010", "name": "水灵", "form": "", "stage": "3"}
        entry, kind = cl.match_pet(row, indexes)
        self.assertEqual(entry["learnset_id"], "ls_a")
        self.assertEqual(kind, "same_number_name_stage")

    def test_ambiguous_different_learnsets_are_not_guessed(self):
        row = {"number": "010", "name": "水灵", "form": "", "stage": "3"}
        entry, kind = cl.match_pet(row, self.indexes)
        self.assertIsNone(entry)
        self.assertIsNone(kind)

    def test_unmatched_pet(self):
        row = {"number": "999", "name": "不存在", "form": "", "stage": "1"}
        entry, kind = cl.match_pet(row, self.indexes)
        self.assertIsNone(entry)
        self.assertIsNone(kind)


class TestCollectSkills(unittest.TestCase):
    def test_merges_sources_and_levels(self):
        learnset = cl.parse_learnsets(SYNTHETIC_LEARNSETS)["learnset_a"]
        skills = {
            "skill_native": make_skill("skill_native", "拍击"),
            "skill_shared": make_skill("skill_shared", "甩水"),
            "skill_blood": make_skill("skill_blood", "水枪"),
            "skill_stone": make_skill("skill_stone", "寒风吹"),
            "skill_feature": make_skill(
                "skill_feature", "最好的伙伴", category="特性",
                damage_class="", power="",
            ),
        }
        records, missing = cl.collect_pet_skills(learnset, skills)

        self.assertEqual(set(records), set(skills))
        self.assertEqual(dict(missing), {"skill_missing": 1})
        self.assertEqual(records["skill_shared"]["sources"], {"native", "stone"})
        self.assertEqual(records["skill_shared"]["levels"], [12])
        self.assertEqual(records["skill_blood"]["bloods"], ["水"])
        self.assertEqual(records["skill_native"]["levels"], [1])
        self.assertEqual(records["skill_feature"]["sources"], {"feature"})

    def test_missing_skill_is_skipped(self):
        learnset = {"skill_stones": ["skill_missing"]}
        records, missing = cl.collect_pet_skills(learnset, {})
        self.assertEqual(records, {})
        self.assertEqual(dict(missing), {"skill_missing": 1})


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestGeneratedLearnsetData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = read_csv(ROOT / "data" / "learnsets.csv")
        cls.pets = read_csv(ROOT / "data" / "pets.csv")
        cls.skills = read_csv(ROOT / "data" / "skills.csv")

    def test_every_pet_has_learnset_rows(self):
        pet_keys = {
            (row["number"], row["name"], row["form"], row["stage"])
            for row in self.pets
        }
        data_keys = {
            (row["number"], row["name"], row["form"], row["stage"])
            for row in self.rows
        }
        self.assertEqual(data_keys, pet_keys)

    def test_known_native_skills(self):
        rows = [
            row for row in self.rows
            if row["name"] == "水灵" and row["skill_name"] == "气泡"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sources"], "native")
        self.assertEqual(rows[0]["level"], "8")
        self.assertEqual(rows[0]["category"], "攻击")

        rows = [
            row for row in self.rows
            if row["name"] == "龙息帕尔" and row["skill_name"] == "极限撕裂"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sources"], "native")
        self.assertEqual(rows[0]["level"], "33")

    def test_skill_stone_source(self):
        rows = [
            row for row in self.rows
            if row["name"] == "龙息帕尔" and row["skill_name"] == "龙吼"
        ]
        self.assertEqual(len(rows), 1)
        self.assertIn("stone", rows[0]["sources"].split("|"))

    def test_blood_source_has_blood_type(self):
        for row in self.rows:
            sources = row["sources"].split("|")
            if "blood" in sources:
                self.assertTrue(row["blood"], row)
            else:
                self.assertEqual(row["blood"], "", row)

    def test_all_rows_point_to_known_skills(self):
        skill_ids = {row["skill_id"] for row in self.skills}
        for row in self.rows:
            self.assertIn(row["skill_id"], skill_ids)
            self.assertTrue(row["skill_name"])
            self.assertTrue(row["category"])
            self.assertTrue(row["sources"])
            if row["category"] == "攻击":
                self.assertIn(row["damage_class"], ("物攻", "魔攻"), row)

    def test_no_duplicate_pet_skill_rows(self):
        keys = [
            (row["number"], row["name"], row["form"], row["stage"], row["skill_id"])
            for row in self.rows
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_pet_has_an_attack_skill(self):
        attack_pets = {
            (row["number"], row["name"], row["form"], row["stage"])
            for row in self.rows
            if row["category"] == "攻击"
        }
        for pet in self.pets:
            key = (pet["number"], pet["name"], pet["form"], pet["stage"])
            self.assertIn(key, attack_pets, f"{pet['name']} 没有攻击技能")


if __name__ == "__main__":
    unittest.main()
