#!/usr/bin/env python3
"""固定区域离线视频采样，以及已复核回合 JSON 的导出。

extract 只输出原始 OCR 证据；export 不重新猜测已复核的身份和回合。
"""

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_config(config, frame_size=None):
    size = config.get("screen_size")
    if (not isinstance(size, list) or len(size) != 2 or
            any(type(n) is not int or n <= 0 for n in size)):
        raise ValueError("screen_size 必须是两个正整数")
    if frame_size is not None and list(frame_size) != size:
        raise ValueError(f"视频尺寸 {list(frame_size)} 与配置 {size} 不一致，需重新校准ROI")
    width, height = size
    def box_valid(box):
        return (isinstance(box, list) and len(box) == 4 and all(type(v) is int for v in box)
                and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)
    viewport = config.get("viewport")
    if not box_valid(viewport):
        raise ValueError("viewport 必须是原视频范围内的矩形")
    if [viewport[2] - viewport[0], viewport[3] - viewport[1]] != config.get("image_size"):
        raise ValueError("viewport 与 image_size 不一致，不能包含标题栏")
    for section in ("hud", "actions", "damage", "energy_timing"):
        cfg = config[section]
        if not isinstance(cfg.get("scale"), (int, float)) or not 0 < cfg["scale"] <= 8:
            raise ValueError(f"{section} scale 必须大于0且不超过8")
        boxes = list(cfg.get("rois", {}).values()) + [s["roi"] for s in cfg.get("samples", []) if "roi" in s]
        if not boxes or any(not box_valid(box) for box in boxes):
            raise ValueError(f"{section} ROI 越界或缺失")


def sampling_jobs(config, kind="all"):
    jobs = []
    def add(section, ident, timestamp, roi):
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("采样时间必须是有限的非负数字")
        cfg = config[section]
        jobs.append({"kind": section, "id": ident, "time_s": timestamp, "roi": roi,
                     "scale": cfg["scale"], "use_det": cfg["use_det"]})
    if kind in ("all", "hud"):
        for t in config["hud"]["times_s"]:
            for name, box in config["hud"]["rois"].items():
                add("hud", name, t, box)
    if kind in ("all", "actions"):
        for anchor in config["actions"]["anchors"]:
            for offset in config["actions"]["offsets_s"]:
                add("actions", anchor["id"], round(anchor["time_s"] + offset, 6),
                    config["actions"]["rois"][anchor["side"]])
    for section in ("damage", "energy_timing"):
        if kind not in ("all", section):
            continue
        for sample in config[section]["samples"]:
            if section == "damage":
                add(section, sample["id"], sample["time_s"], sample["roi"])
            else:
                for name, box in config[section]["rois"].items():
                    add(section, sample["id"] + "_" + name, sample["time_s"], box)
    return sorted(jobs, key=lambda row: (row["time_s"], row["kind"], row["id"]))


def validate_review(review):
    turns = review.get("回合", [])
    if not turns or [t["回合"] for t in turns] != list(range(1, len(turns) + 1)):
        raise ValueError("回合编号须从1开始连续排列")
    identities = []
    for turn in turns:
        for phase in ("行动前", "行动后"):
            state = turn[phase]
            for side in ("我方", "敌方"):
                pet = state[side]
                if not pet.get("精灵"):
                    raise ValueError("状态必须保留出战精灵名")
                numeric = ("生命值", "最大生命值", "能量") if side == "我方" else ("生命百分比", "能量")
                for key in numeric:
                    n = pet.get(key)
                    if n is not None and (type(n) is not int or n < 0):
                        raise ValueError(f"{key} 必须是非负整数或null")
                hp, maximum = pet.get("生命值"), pet.get("最大生命值")
                if hp is not None and maximum is not None and (maximum <= 0 or hp > maximum):
                    raise ValueError("当前生命不能超过最大生命")
                percent = pet.get("生命百分比")
                if percent is not None and percent > 100:
                    raise ValueError("生命百分比不能超过100")
        for event in turn["事件"]:
            if "证据编号" in event:
                identities.append(event["证据编号"])
    if len(identities) != len(set(identities)):
        raise ValueError("同一行动证据不能重复归入多个回合")


def export_review(review, output):
    """导出用户已复核的记录，不将固定样例误称为视频自动识别结果。"""
    validate_review(review)
    output.mkdir(parents=True, exist_ok=True)
    full = deepcopy(review)
    summary = {"视频": full["视频"], "记录状态": full["记录状态"], "说明": full["说明"],
               "回合": [{"回合": t["回合"], "事件": [e["描述"] for e in t["事件"]],
                         "生命与能量": t["生命与能量摘要"]} for t in full["回合"]]}
    write_json(output / "battle.json", full)
    write_json(output / "summary.json", summary)
    (output / "turns").mkdir(exist_ok=True)
    for turn in full["回合"]:
        write_json(output / "turns" / f"turn_{turn['回合']:03d}.json", turn)
    return len(full["回合"])


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_readings(result, roi, scale):
    """纯识别返回值没有boxes；检测框则从放大裁图坐标还原为原视频坐标。"""
    boxes = getattr(result, "boxes", None)
    readings = []
    for i, (text, score) in enumerate(zip(result.txts or (), result.scores or ())):
        item = {"text": text, "confidence": round(float(score), 4)}
        if boxes is not None and i < len(boxes):
            item["source_box"] = [[round(float(x) / scale + roi[0], 2),
                                   round(float(y) / scale + roi[1], 2)] for x, y in boxes[i]]
        readings.append(item)
    return readings


def extract(video, config, output, kind="all", times=None, limit=None, save_crops=False):
    import cv2
    from rapidocr import RapidOCR
    from download_ocr import prepare_config

    validate_config(config)
    jobs = sampling_jobs(config, kind)
    if times:
        jobs = [job for job in jobs if any(abs(job["time_s"] - t) < 1e-6 for t in times)]
    if limit is not None:
        selected = sorted({job["time_s"] for job in jobs})[:limit]
        jobs = [job for job in jobs if job["time_s"] in selected]
    if not jobs:
        raise ValueError("没有匹配到采样时间；--time须对应配置内的采样时刻")
    capture = cv2.VideoCapture(str(video))
    try:
        if not capture.isOpened():
            raise ValueError(f"无法打开视频：{video}")
        size = [round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))]
        validate_config(config, size)
        fps, count = capture.get(cv2.CAP_PROP_FPS), round(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0 or count <= 0:
            raise ValueError("无法取得有效视频帧率及帧数")
        duration = count / fps
        expected = config.get("expected_duration_s")
        if expected is not None and abs(duration - expected) > config.get("duration_tolerance_s", 1):
            raise ValueError("视频时长与本片动作锚点不符，不可套用既有回合时间")
        if any(job["time_s"] >= duration for job in jobs):
            raise ValueError("配置的采样时间超过视频时长")
        # 一次加载CPU模型，只保持当前原始帧和局部裁剪，不缓存完整视频。
        cv2.setNumThreads(2)
        engine = RapidOCR(config_path=str(prepare_config()), params={"Global.log_level": "error", "Det.limit_side_len": 960})
        output.mkdir(parents=True, exist_ok=True)
        if save_crops:
            (output / "crops").mkdir(exist_ok=True)
        records, last_time, frame = [], None, None
        for job in jobs:
            if last_time != job["time_s"]:
                capture.set(cv2.CAP_PROP_POS_MSEC, job["time_s"] * 1000)
                ok, frame = capture.read()
                if not ok:
                    raise ValueError(f"视频解码失败：{job['time_s']}秒")
                last_time = job["time_s"]
            x1, y1, x2, y2 = job["roi"]
            pixels = frame[y1:y2, x1:x2]
            crop_path = None
            if save_crops:
                safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", job["id"])
                crop_path = f"crops/{job['kind']}_{safe_id}_{job['time_s']:09.3f}.png"
                if not cv2.imwrite(str(output / crop_path), pixels):
                    raise OSError(f"无法保存裁剪：{crop_path}")
            scale = job["scale"]
            resized = cv2.resize(pixels, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            result = engine(resized, use_det=job["use_det"], use_cls=False, text_score=.2)
            readings = source_readings(result, job["roi"], scale)
            records.append({**job, "frame_index": round(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1,
                            "readings": readings, **({"crop": crop_path} if crop_path else {})})
        evidence = {"source": {"file": video.name, "screen_size": size, "fps": fps,
                               "frames": count, "duration_s": duration},
                    "mode": "anchored_ocr_evidence", "manual_review_required": True,
                    "coordinate_space": "source_frame", "observations": records}
        write_json(output / "observations.json", evidence)
        return len(records)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("extract", help="按固定ROI与时间采样原片，输出原始OCR证据")
    scan.add_argument("video", type=Path)
    scan.add_argument("--config", type=Path, default=ROOT / "configs/video_reference_hd.json")
    scan.add_argument("--output", type=Path, default=ROOT / ".cache/video_review/evidence")
    scan.add_argument("--kind", choices=["all", "hud", "actions", "damage", "energy_timing"], default="all")
    scan.add_argument("--time", type=float, nargs="+", help="仅运行配置中这些采样时刻")
    scan.add_argument("--limit", type=int, help="最多采样多少个时刻，用于快速校准")
    scan.add_argument("--save-crops", action="store_true")
    export = commands.add_parser("export", help="导出已复核记录；不读取或猜测新视频")
    export.add_argument("--review", type=Path, default=ROOT / "data/battles/reference_hd.json")
    export.add_argument("--output", type=Path, default=ROOT / ".cache/video_review/reviewed")
    args = parser.parse_args()
    try:
        if args.command == "extract":
            if args.limit is not None and args.limit <= 0:
                parser.error("--limit必须为正整数")
            count = extract(args.video, load_json(args.config), args.output,
                            args.kind, args.time, args.limit, args.save_crops)
            print(f"已保存{count}条原始OCR证据：{args.output / 'observations.json'}")
        else:
            count = export_review(load_json(args.review), args.output)
            print(f"已导出{count}个已复核回合：{args.output / 'battle.json'}")
    except (ValueError, OSError, KeyError, TypeError, ImportError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
