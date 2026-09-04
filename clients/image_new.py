"""单次调用图像生成，保存到 outputs。"""

import base64
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "http://gpttap.top/v1"
API_KEY = "sk-Ka00PMpOZ3xiYob65ByRjEo1NvrjHXksP7YBTSUl9FJMXoep"
MODEL = "gpt-image-2"
PROMPT = "帮我生成一张图片，上面要写满各种诗情画意的文字，文字越多越好，至少500字,字体采和微软雅黑"
SIZE = "2560x1440"
QUALITY = "high"
OUTPUT_DIR = Path(__file__).parent / "outputs"


def generate_image() -> bytes:
    url = f"{BASE_URL.rstrip('/')}/images/generations"
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "prompt": PROMPT,
        "n": 1,
        "size": SIZE,
        "quality": QUALITY,
        "response_format": "b64_json",
        "output_format": "png",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=900)
    resp.raise_for_status()
    item = resp.json()["data"][0]
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


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = generate_image()
    path = OUTPUT_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    path.write_bytes(data)
    print(f"已保存: {path}")


if __name__ == "__main__":
    main()
