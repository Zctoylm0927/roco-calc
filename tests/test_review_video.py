import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from review_video import load_json, sampling_jobs, source_readings, validate_config, validate_review

ROOT = Path(__file__).resolve().parents[1]


class VideoReviewTests(unittest.TestCase):
    def test_native_frame_and_title_bar_geometry_is_checked(self):
        config = load_json(ROOT / "configs/video_reference_hd.json")
        validate_config(config, (2560, 1440))
        with self.assertRaises(ValueError):
            validate_config(config, (960, 544))
        config["viewport"][1] -= 30
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_sampling_does_not_accept_out_of_frame_or_nonfinite_time(self):
        config = load_json(ROOT / "configs/video_reference_hd.json")
        config["damage"]["samples"][0]["roi"][2] = 3000
        with self.assertRaises(ValueError):
            validate_config(config)
        config = load_json(ROOT / "configs/video_reference_hd.json")
        config["hud"]["times_s"][0] = float("nan")
        with self.assertRaises(ValueError):
            sampling_jobs(config, "hud")

    def test_recognition_only_output_without_boxes_is_supported(self):
        result = SimpleNamespace(txts=["317/398"], scores=[.99])
        self.assertEqual(source_readings(result, [565, 248, 659, 270], 3),
                         [{"text": "317/398", "confidence": .99}])

    def test_detector_boxes_return_to_original_pixels(self):
        result = SimpleNamespace(txts=["84"], scores=[.98],
                                 boxes=[[[3, 6], [9, 6], [9, 12], [3, 12]]])
        self.assertEqual(source_readings(result, [1500, 450, 2150, 850], 3)[0]["source_box"],
                         [[1501, 452], [1503, 452], [1503, 454], [1501, 454]])

    def test_review_keeps_unknowns_and_rejects_duplicate_event_attribution(self):
        reviewed = load_json(ROOT / "data/battles/reference_hd.json")
        validate_review(reviewed)
        self.assertEqual(len(reviewed["回合"]), 27)
        self.assertEqual(reviewed["回合"][1]["行动后"]["我方"]["生命值"], 317)
        self.assertEqual(reviewed["回合"][1]["行动后"]["我方"]["最大生命值"], 398)
        self.assertEqual(reviewed["回合"][2]["事件"][1]["显示伤害"], 84)
        self.assertEqual(reviewed["回合"][25]["事件"][1]["显示伤害"], 778)
        self.assertIsNone(reviewed["回合"][-1]["行动后"]["敌方"]["能量"])
        original = json.dumps(reviewed, ensure_ascii=False)
        self.assertNotIn("/home/", original)
        changed = copy.deepcopy(reviewed)
        changed["回合"][1]["事件"][0]["证据编号"] = changed["回合"][0]["事件"][1]["证据编号"]
        with self.assertRaises(ValueError):
            validate_review(changed)


if __name__ == "__main__":
    unittest.main()
