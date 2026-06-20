"""
GPT 图像编辑客户端

通过 OpenAI 兼容 API 调用 /v1/images/edits 接口编辑图片。
"""

import argparse
import base64
import json
import logging
import mimetypes
import os
import time
from datetime import datetime
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.json") -> dict:
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件未找到: {config_path}")
    with open(config_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/png"


def edit_image(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    image_path: Path,
    mask_path: Path | None = None,
    size: str | None = None,
    quality: str = "auto",
) -> tuple[bool, float, str | None, str | None]:
    """
    调用 OpenAI 兼容的图像编辑接口（multipart 上传）。
    返回 (是否成功, 响应耗时秒数, 错误信息, b64_json)。
    """
    start = time.time()
    url = f"{base_url.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {api_key}"}

    data = {
        "model": model,
        "prompt": prompt,
        "n": "1",
        "quality": quality,
        "response_format": "b64_json",
    }
    if size:
        data["size"] = size

    image_bytes = image_path.read_bytes()
    if not image_bytes:
        return False, time.time() - start, f"输入图片为空: {image_path}", None

    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("image", (image_path.name, image_bytes, _mime_type(image_path))),
    ]
    if mask_path is not None:
        mask_bytes = mask_path.read_bytes()
        if not mask_bytes:
            return False, time.time() - start, f"蒙版图片为空: {mask_path}", None
        files.append(("mask", (mask_path.name, mask_bytes, _mime_type(mask_path))))

    try:
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=900)
        resp.raise_for_status()
        payload = resp.json()
        b64_json = payload["data"][0].get("b64_json")
        if b64_json:
            return True, time.time() - start, None, b64_json

        error_msg = "响应解析错误: 缺少 b64_json 字段"
        logger.error(error_msg)
        return False, time.time() - start, error_msg, None

    except requests.exceptions.HTTPError as e:
        resp = e.response
        detail = ""
        if resp is not None:
            try:
                body = resp.json()
                err = body.get("error") if isinstance(body, dict) else None
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("code") or "")
                elif isinstance(body, dict) and body.get("error"):
                    detail = str(body["error"])
            except ValueError:
                detail = (resp.text or "").strip()[:300]
        error_msg = f"HTTP 错误: {e}" + (f" – {detail}" if detail else "")
        logger.error(error_msg)
        return False, time.time() - start, error_msg, None

    except requests.exceptions.RequestException as e:
        error_msg = f"请求错误: {e}"
        logger.error(error_msg)
        return False, time.time() - start, error_msg, None

    except (KeyError, IndexError, ValueError) as e:
        error_msg = f"响应解析错误: {e}"
        logger.error(error_msg)
        return False, time.time() - start, error_msg, None


def save_image(b64_json: str, output_dir: Path, prefix: str = "edit") -> Path | None:
    try:
        img_bytes = base64.b64decode(b64_json)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = output_dir / f"{prefix}_{ts}.png"
        while path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = output_dir / f"{prefix}_{ts}.png"
        path.write_bytes(img_bytes)
        return path
    except Exception as e:
        logger.error("保存图片失败: %s", e)
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="调用 GPT 图像编辑接口")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--image", help="待编辑图片路径（覆盖配置文件 edit.input_image）")
    parser.add_argument("--mask", help="蒙版图片路径（可选）")
    parser.add_argument("--prompt", help="编辑提示词（覆盖配置文件 edit.prompt）")
    return parser.parse_args()


def main():
    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    args = parse_args()
    config = load_config(args.config)

    api_cfg = config["api"]
    edit_cfg = config.get("edit", {})
    out_cfg = config.get("output", {})

    image_path = Path(args.image or edit_cfg.get("input_image") or "")
    if not image_path:
        raise SystemExit("请通过 --image 或配置文件 edit.input_image 指定输入图片")
    if not image_path.is_file():
        raise SystemExit(f"输入图片不存在: {image_path}")

    prompt = args.prompt or edit_cfg.get("prompt")
    if not prompt:
        raise SystemExit("请通过 --prompt 或配置文件 edit.prompt 指定编辑提示词")

    mask_raw = args.mask or edit_cfg.get("mask_image")
    mask_path = Path(mask_raw) if mask_raw else None
    if mask_path is not None and not mask_path.is_file():
        raise SystemExit(f"蒙版图片不存在: {mask_path}")

    output_dir = Path(out_cfg.get("base_output_dir", "outputs"))

    logger.info("开始图像编辑")
    logger.info("  模型      : %s", api_cfg["model"])
    logger.info("  输入图片  : %s", image_path)
    logger.info("  蒙版      : %s", mask_path or "无")
    logger.info("  提示词    : %s", prompt[:80])
    logger.info("  输出目录  : %s", output_dir)

    success, elapsed, error_msg, b64_json = edit_image(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
        model=api_cfg["model"],
        prompt=prompt,
        image_path=image_path,
        mask_path=mask_path,
        size=api_cfg.get("image_size"),
        quality=api_cfg.get("image_quality", "auto"),
    )

    if not success:
        logger.error("图像编辑失败 (%.2f 秒): %s", elapsed, error_msg)
        raise SystemExit(1)

    saved_path = save_image(b64_json, output_dir) if b64_json else None
    if saved_path:
        logger.info("图像编辑成功 (%.2f 秒), 已保存: %s", elapsed, saved_path)
    else:
        logger.error("图像编辑成功 (%.2f 秒), 但保存失败", elapsed)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
