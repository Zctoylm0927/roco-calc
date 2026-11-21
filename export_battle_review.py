"""将离线 OCR 证据导出为待复核的对战记录；不推断未观察到的回合。

输入由视频采样工具产生。本工具只负责整理证据，不是完整的视频识别器。
"""

import argparse
import csv
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_actions(rows, skill_names=()):
    actions = []
    for side in ("our", "opponent"):
        groups = []
        for row in rows:
            readings = row["regions"].get(side + "_log", [])
            text = " ".join(item["text"] for item in readings)
            # 已复核的 OCR 混淆字；候选仍保留 needs_review 与原文。
            switch_marker = "召唤" in text or re.search(r"召[哦晚]了", text)
            kind = "switch" if switch_marker else "skill" if "使出" in text else None
            if kind is None:
                continue
            observation = {"frame": row["frame"], "time_s": row["time"], "readings": readings}
            if groups and groups[-1]["type"] == kind and row["time"] - groups[-1]["last_seen_s"] <= 1:
                group = groups[-1]
            else:
                group = {"side": side, "type": kind, "first_seen_s": row["time"], "evidence": []}
                groups.append(group)
            group["last_seen_s"] = row["time"]
            group["evidence"].append(observation)
        actions.extend(groups)
    actions.sort(key=lambda item: (item["first_seen_s"], item["side"]))
    for index, action in enumerate(actions, 1):
        action["id"] = f"action_{index:03d}"
        action["round_number"] = None
        action["status"] = "needs_review"
        texts = [" ".join(x["text"] for x in observation["readings"]) for observation in action["evidence"]]
        costs = []
        for text in texts:
            # 只读星号紧邻的整数，不将等级或数据库基础能耗当成实际能耗。
            costs.extend(int(value) for value in re.findall(r"[★☆]\s*(\d{1,2})(?!\d)", text))
        cost = Counter(costs).most_common(1)[0][0] if costs else None
        action["actor"] = {"pet_id": None, "original_name": None, "display_name": None}
        action["skill"] = {"name": None, "name_candidates": [], "observed_energy_cost": cost} if action["type"] == "skill" else None
        action["forced"] = None if action["type"] == "switch" else False
        action["consumes_normal_action"] = None
        action["before"] = unknown_state()
        action["after"] = unknown_state()
        if action["type"] == "skill":
            suffixes = [text.split("使出", 1)[1].lstrip("了") for text in texts]
            names = Counter()
            for suffix in suffixes:
                matches = [name for name in skill_names if name in suffix]
                if matches:
                    names[max(matches, key=len)] += 1
            if names:
                ordered = names.most_common()
                action["skill"]["name_candidates"] = [name for name, _ in ordered]
                if len(ordered) == 1 or ordered[0][1] > ordered[1][1]:
                    action["skill"]["name"] = ordered[0][0]
            if any("聚能" in suffix for suffix in suffixes):
                action["type"] = "gather_energy"
                action["skill"] = None
                action["energy_restore_by_rule"] = 5
                action["observed_energy_change"] = None
            elif cost == 0 and any("能" in suffix for suffix in suffixes):
                action["type_candidates"] = ["gather_energy", "skill"]
            raw_names = [re.sub(r"^(?:完美的|勇者|低沉的|逐风的)", "", text.split("使出", 1)[0]) for text in texts]
            action["actor"]["raw_display_name_candidates"] = list(dict.fromkeys(raw_names))
        else:
            action["switch_to"] = {"pet_id": None, "original_name": None, "display_name": None,
                                   "raw_name_candidates": list(dict.fromkeys(
                                       re.split(r"召[唤哦晚]", text, maxsplit=1)[1].lstrip("了").rstrip("！!") for text in texts))}
        best_observation = max(action["evidence"], key=lambda observation: sum(
            x["score"] for x in observation["readings"]
        ) / max(1, len(observation["readings"])))
        action["summary"] = ("我方" if action["side"] == "our" else "敌方") + "：" + " ".join(
            x["text"] for x in best_observation["readings"])
    # 同一采样时刻不等于真实同时行动，列表顺序不能代替可靠的先后关系。
    for action in actions:
        action["order_status"] = "unresolved_same_sample" if any(
            other["id"] != action["id"] and other["first_seen_s"] == action["first_seen_s"]
            for other in actions
        ) else "first_observed_order_only"
    return actions


def candidate_turns(actions):
    """相同一方再次出现提示时切组；仅用于复核导航，不能作为正式回合编号。"""
    groups = []
    current = []
    sides = set()
    for action in actions:
        if action["side"] in sides:
            groups.append(current)
            current, sides = [], set()
        current.append(action)
        sides.add(action["side"])
    if current:
        groups.append(current)
    return [{
        "candidate_id": f"candidate_{i:03d}",
        "round_number": None,
        "status": "boundary_unverified",
        "action_ids": [a["id"] for a in group],
        "first_seen_s": group[0]["first_seen_s"],
        "last_seen_s": group[-1]["last_seen_s"],
        "before": unknown_state(),
        "after": unknown_state(),
    } for i, group in enumerate(groups, 1)]


def unknown_state():
    return {side: {"pet_id": None, "original_name": None, "display_name": None,
                   "hp": None, "max_hp": None, "hp_percent": None, "energy": None}
            for side in ("our", "opponent")}


def damage_observations(report):
    result = []
    for event in report["events"]:
        readings = [r for r in report["numeric_readings"] if r["event"] == event["id"]]
        result.append({
            "id": f"damage_clip_{event['id']:02d}",
            "start_s": event["start_s"], "end_s": event["end_s"],
            "round_number": None, "caused_by_action_id": None, "target_side": None,
            "status": "needs_action_and_target_association",
            "readings": [{"value": r["value"], "source_frames": r["frames"]} for r in readings],
            "total_damage": None,
            "note": "浮字读数；多次浮字是否独立伤害、是否可相加仍待确认。空列表表示没有可靠数值，并非零伤害。",
        })
    return result


def apply_review(result, review, pet_catalog=()):
    """合并人工确认；只更新指定事件的指定字段，保留动作及数值的不确定性。"""
    if review["source_file"] != result["source"]["file"]:
        raise ValueError("人工确认文件与视频来源不匹配")
    resolutions = {item["question_id"]: item for item in review.get("resolutions", [])}
    for question in result["review_questions"]:
        resolution = resolutions.get(question["id"])
        if resolution:
            question.update(status="resolved", answer=resolution["answer"],
                            confirmation_source=resolution.get("confirmation_source", "user"))
        else:
            question["status"] = "open"
    for confirmation in review.get("action_confirmations", []):
        matches = [action for action in result["action_observations"]
                   if action["side"] == confirmation["side"]
                   and abs(action["first_seen_s"] - confirmation["first_seen_s"]) < .01]
        if len(matches) != 1:
            raise ValueError(f"人工确认无法唯一对应行动：{confirmation}")
        action = matches[0]
        identity = action[confirmation["field"]]
        name = confirmation["original_name"]
        catalog_matches = [pet for pet in pet_catalog if pet["name"] == name]
        ids = {pet["pet_id"] for pet in catalog_matches}
        identity.update(original_name=name, identity_source="user_confirmed",
                        pet_id=next(iter(ids)) if len(ids) == 1 else None,
                        database_status="present" if catalog_matches else "missing",
                        identity_status="confirmed")
        snapshot = action["after"] if confirmation["field"] == "switch_to" else action["before"]
        snapshot[action["side"]].update(original_name=name, pet_id=identity["pet_id"],
                                         identity_source="user_confirmed")
        # 原始名字的确认不等于昵称或皮肤名称也已确认。
        if "appearance" in confirmation:
            identity["appearance"] = deepcopy(confirmation["appearance"])
        if "carried_skill" in confirmation:
            identity["carried_skill"] = confirmation["carried_skill"]
            identity["carried_skill_source"] = "user_confirmed"
            if confirmation["field"] == "actor" and action["skill"]:
                action["skill"]["access_source"] = {
                    "type": "borrowed", "via": confirmation["carried_skill"],
                    "confirmation_source": "user",
                }
        action.setdefault("confirmed_fields", []).append(confirmation["field"] + ".original_name")
        action.setdefault("raw_summary", action["summary"])
        side_name = "我方" if action["side"] == "our" else "敌方"
        if confirmation["field"] == "switch_to":
            action["summary"] = f"{side_name}切换上场：{name}（是否强制待确认）"
        elif action["skill"] and action["skill"]["name"]:
            action["summary"] = f"{side_name}{name}使用{action['skill']['name']}"
    result["confirmed_facts"] = deepcopy(review)
    result["identity_distinctions"] = deepcopy(review.get("identity_distinctions", []))
    result["rules"]["dynamic_skill_access"] = {
        "mechanisms": review.get("dynamic_skill_mechanisms", []),
        "native_skill_pool_is_exhaustive": False,
        "note": "复写、借用、取念可使当前技能超出原生技能池；不能仅据此否定画面读数。",
    }
    if "damage_rules" in review:
        result["rules"]["damage"] = deepcopy(review["damage_rules"])
    for confirmation in review.get("damage_confirmations", []):
        matches = [item for item in result.get("damage_observations", []) if item["id"] == confirmation["id"]]
        if len(matches) != 1:
            raise ValueError(f"伤害确认无法唯一对应片段：{confirmation['id']}")
        matches[0].update(deepcopy(confirmation))
    for observation in review.get("additional_damage_observations", []):
        item = deepcopy(observation)
        if any(existing["id"] == item["id"] for existing in result["damage_observations"]):
            raise ValueError(f"重复的补充伤害片段：{item['id']}")
        key = item.pop("action_key")
        actions = [action for action in result["action_observations"]
                   if action["side"] == key["side"] and abs(action["first_seen_s"] - key["first_seen_s"]) < .01]
        if len(actions) != 1:
            raise ValueError(f"补充伤害无法唯一对应行动：{key}")
        item["caused_by_action_id"] = actions[0]["id"]
        result["damage_observations"].append(item)


def export_review(cache_dir, output, review_path=None):
    rows = read_jsonl(cache_dir / "turn_text.jsonl")
    sampling = json.loads((cache_dir / "sampling_report.json").read_text(encoding="utf-8"))
    skill_path = Path(__file__).resolve().parent / "data/skills.csv"
    with skill_path.open(encoding="utf-8-sig", newline="") as source:
        skill_names = [row["name"] for row in csv.DictReader(source)]
    actions = collect_actions(rows, skill_names)
    result = {
        "schema_version": "0.1-review",
        "status": "incomplete_review_draft",
        "source": {"file": "参考作战视频.mp4", **deepcopy(sampling["source"])},
        "quality": {
            "action_observation_groups": len(actions), "verified_turn_count": 0,
            "exhaustive": False,
            "limitations": [
                "行动提示按2fps采样，短提示可能遗漏；first_seen_s是首次采样读到的时刻，不是动作起始时刻。",
                "candidate_turns仅供导航；尚未确认强制切换及漏读行动，不可作为正式回合。",
                "仅人工确认的精灵身份已写入；其他提示中的名字不能直接视为原始名字。",
                "双方行动前后HP和能量尚未可靠关联；未知值保留null。",
                "同一首次采样时刻的双方行动顺序未确认。",
            ],
        },
        "rules": {
            "team_size": 6, "normal_actions": ["skill", "gather_energy", "switch"],
            "gather_energy_restore": 5, "leader_item_uses_per_side": 1,
            "leader_item_consumes_normal_action": False,
            "forced_switch": {"belongs_to_current_turn": True,
                              "when_already_acted": "保留已经发生的行动，追加本回合强制切换。",
                              "when_not_yet_acted": "以本回合强制切换替代未执行行动。"},
        },
        "turns": [],
        "candidate_turns": candidate_turns(actions),
        "action_observations": actions,
        "damage_observations": damage_observations(sampling),
        "animation_observations": [
            {"time_s": 55, "candidate_type": "leader_transform", "candidate_side": "our",
             "status": "needs_turn_and_identity_association", "evidence_image": "detail_55.png"},
            {"time_s": 150, "candidate_type": "leader_transform", "candidate_side": "opponent",
             "status": "needs_turn_and_identity_association", "evidence_image": "detail_150.png"},
        ],
        "hud_observations": [{"frame": row["frame"], "time_s": row["time"],
                              "our": row["regions"].get("our_hud", []),
                              "opponent": row["regions"].get("opponent_hud", [])}
                             for row in rows if "our_hud" in row["regions"]],
        "review_questions": [
            {"id": "copied_skills", "times_s": [177.5, 507.5],
             "question": "寂灭骨龙使用冬至及踩地，是否来自借用或其他机制？"},
            {"id": "unknown_our_pet", "times_s": [209.5, 243],
             "question": "这两次我方召唤的精灵原始名字是什么？"},
            {"id": "opponent_abu", "times_s": [87],
             "question": "敌方阿布是否为自定义名字，原始身份是什么？"},
            {"id": "repeated_summon", "times_s": [392.5],
             "question": "核对06:32前后的上场精灵及是否遗漏中间的切换提示。"},
        ],
    }
    if review_path is not None:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        with (skill_path.parent / "learnsets.csv").open(encoding="utf-8-sig", newline="") as source:
            pet_catalog = list(csv.DictReader(source))
        apply_review(result, review, pet_catalog)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/video_analysis"))
    parser.add_argument("--output", type=Path, default=Path(".cache/video_analysis/battle_review.json"))
    parser.add_argument("--review", type=Path, help="指定视频的人工确认 JSON；按时间和阵营关联事件")
    args = parser.parse_args()
    result = export_review(args.cache_dir, args.output, args.review)
    print(f"已写入 {args.output}，{len(result['action_observations'])} 组行动提示；正式回合仍待复核。")


if __name__ == "__main__":
    main()
