"""单次调用图像编辑，保存到 outputs。"""

import base64
import mimetypes
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000/v1"
API_KEY = "Abcd@19860202"
MODEL = "gpt-image-2"
PROMPT = "改成盛夏晴天"
SIZE = "auto"
QUALITY = "high"
INPUT_IMAGE = Path(__file__).parent / "outputs" / "20260909_104840.png"
MASK_IMAGE = None
OUTPUT_DIR = Path(__file__).parent / "outputs"


def _mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "image/png"


def _image_bytes_from_item(item: dict) -> bytes:
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    image_url = item.get("url") or ""
    if image_url.startswith("data:") and "," in image_url:
        return base64.b64decode(image_url.split(",", 1)[1])
    if image_url.startswith("http"):
        img = requests.get(image_url, timeout=200)
        img.raise_for_status()
        return img.content
    raise ValueError("响应缺少图片数据")


def edit_image() -> bytes:
    url = f"{BASE_URL.rstrip('/')}/images/edits"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": MODEL,
        "prompt": PROMPT,
        "n": "1",
        "size": SIZE,
        "quality": QUALITY,
        "response_format": "b64_json",
        "output_format": "png",
    }
    files = [("image", (INPUT_IMAGE.name, INPUT_IMAGE.read_bytes(), _mime_type(INPUT_IMAGE)))]
    if MASK_IMAGE is not None:
        mask_path = Path(MASK_IMAGE)
        files.append(("mask", (mask_path.name, mask_path.read_bytes(), _mime_type(mask_path))))

    resp = requests.post(url, headers=headers, data=data, files=files, timeout=900)
    if not resp.ok:
        print(resp.status_code, resp.text)
        resp.raise_for_status()
    return _image_bytes_from_item(resp.json()["data"][0])


def main():
    if not INPUT_IMAGE.is_file():
        raise SystemExit(f"输入图片不存在: {INPUT_IMAGE}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = edit_image()
    path = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path.write_bytes(data)
    print(f"已保存: {path}")


if __name__ == "__main__":
    main()
