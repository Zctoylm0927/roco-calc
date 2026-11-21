#!/usr/bin/env python3
"""下载 PP-OCRv4 中文轻量检测/识别模型，生成本机 CPU 配置。

在 OCR Conda 环境中运行：python download_ocr.py
可选验证：python download_ocr.py --image 一张图片.png
本脚本只准备 OCR，不执行游戏状态识别或写入战斗记录。
"""

import argparse
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "ocr"
CONFIG_PATH = ROOT / ".cache" / "ocr.yaml"


def load_image(path, crop=None, scale=1.0):
    """先裁剪再放大，避免整图缩放使技能名称丢失细节。"""
    from PIL import Image

    if not math.isfinite(scale) or not 0 < scale <= 8:
        raise ValueError("放大倍数必须大于 0 且不超过 8。")
    with Image.open(path) as source:
        image = source.convert("RGB")
    if crop is not None:
        left, top, right, bottom = crop
        if not (0 <= left < right <= image.width and
                0 <= top < bottom <= image.height):
            raise ValueError("裁剪坐标必须位于图片内，且右下坐标大于左上坐标。")
        image = image.crop(crop)
    if scale != 1:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


def prepare_config():
    """保留所固定 RapidOCR 版本的默认字段，显式选择 v4 mobile CPU。"""
    import rapidocr
    import yaml

    default = Path(rapidocr.__file__).parent / "config.yaml"
    config = yaml.safe_load(default.read_text(encoding="utf-8"))
    config["Global"].update(
        model_root_dir=str(MODEL_DIR), use_cls=False
    )
    config["EngineConfig"]["onnxruntime"].update(
        intra_op_num_threads=2,
        inter_op_num_threads=1,
        use_cuda=False,
        use_dml=False,
        use_cann=False,
        use_coreml=False,
    )
    for section in ("Det", "Rec"):
        config[section].update(
            engine_type="onnxruntime", lang_type="ch",
            model_type="mobile", ocr_version="PP-OCRv4",
        )
    config["Det"].update(
        mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225],
        limit_type="max", limit_side_len=736,
    )
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return CONFIG_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="下载后识别一张本地图片")
    parser.add_argument("--crop", type=int, nargs=4,
                        metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
                        help="只识别原图中指定的矩形区域")
    parser.add_argument("--scale", type=float, default=1, help="裁剪后放大倍数")
    parser.add_argument(
        "--recognition-only", action="store_true",
        help="图片已经裁成单行文字时，跳过文字检测",
    )
    args = parser.parse_args()
    if args.image is not None and not args.image.is_file():
        parser.error(f"找不到图片：{args.image}")
    if args.crop is not None and args.image is None:
        parser.error("--crop 需要同时指定 --image")
    image = None
    if args.image is not None:
        try:
            image = load_image(args.image, args.crop, args.scale)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))

    try:
        from rapidocr import RapidOCR, download_models
    except ImportError:
        parser.exit(1, "请先激活 OCR 环境并安装 requirements-ocr.txt。\n")

    config_path = prepare_config()
    download_models(config_path)
    print(f"CPU 配置：{config_path}")
    if args.image is not None:
        engine = RapidOCR(config_path=str(config_path))
        result = engine(image, use_det=not args.recognition_only)
        for text, score in zip(result.txts or (), result.scores or ()):
            print(f"{text}\t置信度 {score:.3f}")


if __name__ == "__main__":
    main()
