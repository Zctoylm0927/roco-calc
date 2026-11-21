import unittest

from copy import deepcopy

from export_battle_review import apply_review, candidate_turns, collect_actions


def row(time, our="", opponent=""):
    return {"time": time, "frame": int(time * 22), "regions": {
        "our_log": [{"text": our, "score": .99}] if our else [],
        "opponent_log": [{"text": opponent, "score": .99}] if opponent else [],
    }}


class BattleReviewTests(unittest.TestCase):
    def test_actual_cost_and_copied_skill_preserved(self):
        actions = collect_actions([row(1, "寂灭骨龙使出了★5冬至！")], ["冬至"])
        self.assertEqual(actions[0]["skill"]["observed_energy_cost"], 5)
        self.assertEqual(actions[0]["skill"]["name"], "冬至")
        self.assertIsNone(actions[0]["actor"]["original_name"])

    def test_level_is_not_energy_and_unknown_is_not_zero(self):
        actions = collect_actions([row(1, "精灵使出了炎枪！ 阿布62级")], ["炎枪"])
        self.assertIsNone(actions[0]["skill"]["observed_energy_cost"])
        self.assertIsNone(actions[0]["after"]["our"]["energy"])

    def test_gather_and_zero_cost_skill_are_distinct(self):
        actions = collect_actions([row(1, "甲使出了★0聚能！"), row(3, "甲使出了★0风吹雪！")], ["风吹雪"])
        self.assertEqual([a["type"] for a in actions], ["gather_energy", "skill"])
        self.assertIsNone(actions[0]["observed_energy_change"])

    def test_ocr_summon_variants_keep_intermediate_switch_and_distinct_names(self):
        actions = collect_actions([
            row(1, opponent="玩家召唤了阿布！"),
            row(3, opponent="玩家召哦了椰浆布丁！"),
            row(3.5, opponent="玩家召晚了椰浆布丁！"),
            row(6, opponent="玩家召唤了布灵布灵！"),
        ])
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[1]["first_seen_s"], 3)
        self.assertEqual(len(actions[1]["evidence"]), 2)
        self.assertEqual(actions[1]["switch_to"]["raw_name_candidates"], ["椰浆布丁"])
        self.assertEqual(actions[0]["switch_to"]["raw_name_candidates"], ["阿布"])
        self.assertEqual(actions[2]["switch_to"]["raw_name_candidates"], ["布灵布灵"])
        self.assertIsNone(actions[1]["forced"])

    def test_persistent_toast_deduplicated_and_simultaneous_order_unresolved(self):
        actions = collect_actions([row(1, "甲使出了炎枪！", "乙使出了炎枪！"), row(1.5, "甲使出了炎枪！")])
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["order_status"], "unresolved_same_sample")

    def test_same_side_switch_does_not_claim_new_verified_round(self):
        actions = collect_actions([row(1, "甲使出了炎枪！"), row(4, opponent="乙使出了炎枪！"), row(7, "玩家召唤了丙！")])
        self.assertIsNone(actions[2]["forced"])
        self.assertIsNone(actions[2]["consumes_normal_action"])
        self.assertTrue(all(group["round_number"] is None for group in candidate_turns(actions)))


    def test_user_identity_missing_database_and_skin_preserve_unknowns(self):
        actions = collect_actions([row(1, opponent="玩家召唤了阿布！"), row(3, "玩家召唤了误读名字！")])
        result = {"source": {"file": "sample.mp4"}, "review_questions": [{"id": "identity"}],
                  "action_observations": actions, "rules": {}}
        original_evidence = deepcopy([a["evidence"] for a in actions])
        review = {"source_file": "sample.mp4", "resolutions": [{"question_id": "identity", "answer": "已确认"}],
                  "action_confirmations": [
                      {"side": "opponent", "first_seen_s": 1, "field": "switch_to", "original_name": "阿布"},
                      {"side": "our", "first_seen_s": 3, "field": "switch_to", "original_name": "月牙雪熊",
                       "appearance": {"is_skin": True, "skin_name": None, "avatar_database_status": "pending_sync"}}]}
        apply_review(result, review, [{"name": "月牙雪熊", "pet_id": "test_pet"}])
        self.assertEqual(actions[0]["switch_to"]["original_name"], "阿布")
        self.assertIsNone(actions[0]["switch_to"]["pet_id"])
        self.assertEqual(actions[0]["switch_to"]["database_status"], "missing")
        self.assertEqual(actions[1]["after"]["our"]["pet_id"], "test_pet")
        self.assertIsNone(actions[1]["switch_to"]["appearance"]["skin_name"])
        self.assertIsNone(actions[1]["forced"])
        self.assertIsNone(actions[1]["after"]["our"]["hp"])
        self.assertEqual([a["evidence"] for a in actions], original_evidence)
        self.assertEqual(result["review_questions"][0]["status"], "resolved")

    def test_borrowed_skill_keeps_observed_cost(self):
        actions = collect_actions([row(1, "寂灭骨龙使出了★5冬至！")], ["冬至"])
        result = {"source": {"file": "sample.mp4"}, "review_questions": [], "action_observations": actions, "rules": {}}
        apply_review(result, {"source_file": "sample.mp4", "dynamic_skill_mechanisms": ["复写", "借用", "取念"],
                             "action_confirmations": [{"side": "our", "first_seen_s": 1, "field": "actor",
                                                       "original_name": "寂灭骨龙", "carried_skill": "借用"}]})
        self.assertEqual(actions[0]["skill"]["access_source"]["via"], "借用")
        self.assertEqual(actions[0]["skill"]["observed_energy_cost"], 5)
        self.assertFalse(result["rules"]["dynamic_skill_access"]["native_skill_pool_is_exhaustive"])
        self.assertEqual(actions[0]["status"], "needs_review")

    def test_review_cannot_silently_apply_to_wrong_source_or_timestamp(self):
        result = {"source": {"file": "sample.mp4"}, "review_questions": [], "action_observations": [], "rules": {}}
        with self.assertRaises(ValueError):
            apply_review(result, {"source_file": "other.mp4"})
        with self.assertRaises(ValueError):
            apply_review(result, {"source_file": "sample.mp4", "action_confirmations": [
                {"side": "our", "first_seen_s": 1, "field": "actor", "original_name": "甲"}]})


if __name__ == "__main__":
    unittest.main()
