"""
GPT 图像生成客户端

通过 OpenAI 兼容 API 使用 gpt-image-2 模型生成图像（单次调用）。
提示词从 prompt.txt 读取。
"""

import argparse
import base64
import json
import logging
import os
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

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


def load_prompt(prompt_path: str = "prompt.txt") -> str:
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"提示词文件未找到: {prompt_path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"提示词文件为空: {prompt_path}")
    return text


def check_image_size(b64_json: str, expected_size: str) -> tuple[bool, str | None]:
    """校验生成图片的实际尺寸是否与期望一致。"""
    try:
        expected_w, expected_h = (int(part) for part in expected_size.lower().split("x", 1))
    except ValueError:
        return False, f"期望尺寸格式无效: {expected_size}"

    try:
        img_bytes = base64.b64decode(b64_json)
        with Image.open(BytesIO(img_bytes)) as img:
            actual_w, actual_h = img.size
    except Exception as e:
        return False, f"图片尺寸检测失败: {e}"

    if actual_w == expected_w and actual_h == expected_h:
        return True, None
    return False, f"图片尺寸不符: 期望 {expected_w}x{expected_h}, 实际 {actual_w}x{actual_h}"


def generate_image(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    size: str,
    quality: str,
) -> tuple[bool, float, str | None, str | None]:
    """
    调用 OpenAI 兼容的图像生成接口。
    返回 (是否成功, 响应耗时秒数, 错误信息, b64_json)。
    """
    start = time.time()
    url = f"{base_url.rstrip('/')}/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "response_format": "b64_json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=900)
        resp.raise_for_status()
        data = resp.json()
        b64_json = data["data"][0].get("b64_json")
        if b64_json:
            size_ok, size_error = check_image_size(b64_json, size)
            if not size_ok:
                logger.error(size_error)
                return False, time.time() - start, size_error, None
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


def save_generated_image(b64_json: str, output_dir: Path) -> Path | None:
    """将 base64 图片解码并保存到 output_dir，文件名以时间戳命名。"""
    try:
        img_bytes = base64.b64decode(b64_json)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{ts}.png"
        while path.exists():
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = output_dir / f"{ts}.png"
        with open(path, "wb") as f:
            f.write(img_bytes)
        return path
    except Exception as e:
        logger.error("保存图片失败: %s", e)
        return None


def main():
    parser = argparse.ArgumentParser(description="GPT 图像生成（单次调用）")
    parser.add_argument("--config", default="config.json", help="API 配置文件路径")
    parser.add_argument("--prompt", default="prompt.txt", help="提示词文件路径")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    os.chdir(script_dir)

    config = load_config(args.config)
    prompt = load_prompt(args.prompt)
    api_cfg = config["api"]
    out_cfg = config.get("output", {})
    output_dir = Path(out_cfg.get("base_output_dir", "outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("开始生成图像")
    logger.info("  模型   : %s", api_cfg["model"])
    logger.info("  尺寸   : %s", api_cfg["image_size"])
    logger.info("  提示词 : %s", prompt[:80] + ("..." if len(prompt) > 80 else ""))

    success, response_time, error_msg, b64_json = generate_image(
        base_url=api_cfg["base_url"],
        api_key=api_cfg["api_key"],
        model=api_cfg["model"],
        prompt=prompt,
        size=api_cfg["image_size"],
        quality=api_cfg["image_quality"],
    )

    if not success:
        logger.error("生成失败 (%.2f 秒): %s", response_time, error_msg)
        raise SystemExit(1)

    saved_path = save_generated_image(b64_json, output_dir) if b64_json else None
    if saved_path:
        logger.info("生成成功 (%.2f 秒), 已保存: %s", response_time, saved_path)
    else:
        logger.error("生成成功 (%.2f 秒), 但保存失败", response_time)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
