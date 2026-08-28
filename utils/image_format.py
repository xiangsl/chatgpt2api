from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

from PIL import Image

OUTPUT_FORMATS = {"png", "jpeg", "webp"}
JPEG_HEADER = b"\xff\xd8\xff"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
WEBP_HEADER = b"RIFF"


def normalize_output_format(value: object, default: str = "png") -> str:
    text = str(value or default).strip().lower()
    if text in {"jpg", "jpeg"}:
        return "jpeg"
    if text in OUTPUT_FORMATS:
        return text
    raise ValueError(f"output_format must be one of: {', '.join(sorted(OUTPUT_FORMATS))}")


def parse_output_compression(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        compression = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("output_compression must be an integer between 0 and 100") from exc
    if compression < 0 or compression > 100:
        raise ValueError("output_compression must be an integer between 0 and 100")
    return compression


def output_format_from_bytes(data: bytes) -> str:
    payload = bytes(data or b"")
    if payload.startswith(JPEG_HEADER):
        return "jpeg"
    if payload.startswith(PNG_HEADER):
        return "png"
    if len(payload) >= 12 and payload.startswith(WEBP_HEADER) and payload[8:12] == b"WEBP":
        return "webp"
    return "png"


def extension_for_format(output_format: str) -> str:
    return "jpg" if output_format == "jpeg" else output_format


def extension_for_bytes(data: bytes) -> str:
    return f".{extension_for_format(output_format_from_bytes(data))}"


def mime_type_for_format(output_format: str) -> str:
    return "image/jpeg" if output_format == "jpeg" else f"image/{output_format}"


def mime_type_from_bytes(data: bytes) -> str:
    return mime_type_for_format(output_format_from_bytes(data))


def mime_type_from_base64(value: str) -> str:
    prefix = str(value or "").strip()[:24]
    if not prefix:
        return "image/png"
    prefix += "=" * (-len(prefix) % 4)
    try:
        return mime_type_from_bytes(base64.b64decode(prefix))
    except Exception:
        return "image/png"


def encode_image_bytes(
    image_bytes: bytes,
    *,
    output_format: str = "png",
    width: int | None = None,
    height: int | None = None,
) -> bytes:
    target_format = normalize_output_format(output_format)
    with Image.open(BytesIO(image_bytes)) as image:
        size = image.size
        target_size = (
            width if width and width > 0 else size[0],
            height if height and height > 0 else size[1],
        )
        current_format = output_format_from_bytes(image_bytes)
        if size == target_size and current_format == target_format:
            return image_bytes
        prepared = _prepare_pil_image(image, target_format)
        if prepared.size != target_size:
            prepared = prepared.resize(target_size, Image.Resampling.LANCZOS)
        return _save_pil_image(prepared, target_format)


def _prepare_pil_image(image: Image.Image, output_format: str) -> Image.Image:
    if output_format != "jpeg":
        return image.copy() if image.mode in {"P", "LA"} else image
    has_alpha = image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info)
    if has_alpha:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background.convert("RGB")
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _save_pil_image(image: Image.Image, output_format: str) -> bytes:
    buffer = BytesIO()
    save_kwargs: dict[str, Any] = {}
    if output_format == "jpeg":
        save_kwargs = {"quality": 100, "subsampling": 0, "optimize": True}
    elif output_format == "webp":
        save_kwargs = {"lossless": True, "quality": 100, "method": 6}
    elif output_format == "png":
        save_kwargs = {"compress_level": 1}
    image.save(buffer, format=output_format.upper(), **save_kwargs)
    return buffer.getvalue()
