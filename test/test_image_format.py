from __future__ import annotations

import base64
import unittest
from io import BytesIO

from PIL import Image

from utils.image_format import (
    encode_image_bytes,
    extension_for_bytes,
    mime_type_from_base64,
    mime_type_from_bytes,
    normalize_output_format,
    output_format_from_bytes,
)


def _image_bytes(fmt: str, width: int = 16, height: int = 8, *, alpha: bool = False) -> bytes:
    mode = "RGBA" if alpha else "RGB"
    color = (255, 0, 0, 128) if alpha else (255, 0, 0)
    image = Image.new(mode, (width, height), color=color)
    buffer = BytesIO()
    save_fmt = "JPEG" if fmt == "jpeg" else fmt.upper()
    image.save(buffer, format=save_fmt)
    return buffer.getvalue()


class ImageFormatTests(unittest.TestCase):
    def test_normalize_accepts_jpg_alias(self) -> None:
        self.assertEqual(normalize_output_format("JPG"), "jpeg")
        self.assertEqual(normalize_output_format(None), "png")

    def test_sniff_jpeg_and_webp(self) -> None:
        jpeg = _image_bytes("jpeg")
        webp = _image_bytes("webp")
        self.assertEqual(output_format_from_bytes(jpeg), "jpeg")
        self.assertEqual(extension_for_bytes(jpeg), ".jpg")
        self.assertEqual(mime_type_from_bytes(jpeg), "image/jpeg")
        self.assertEqual(output_format_from_bytes(webp), "webp")

    def test_sniff_mime_from_base64_prefix(self) -> None:
        jpeg = base64.b64encode(_image_bytes("jpeg")).decode("ascii")
        webp = base64.b64encode(_image_bytes("webp")).decode("ascii")
        self.assertEqual(mime_type_from_base64(jpeg), "image/jpeg")
        self.assertEqual(mime_type_from_base64(webp), "image/webp")

    def test_png_converts_to_jpeg(self) -> None:
        encoded = encode_image_bytes(_image_bytes("png", 32, 16), output_format="jpeg")
        self.assertEqual(output_format_from_bytes(encoded), "jpeg")
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.size, (32, 16))
            self.assertEqual(image.format, "JPEG")

    def test_jpeg_passthrough_when_size_matches(self) -> None:
        original = _image_bytes("jpeg", 24, 24)
        encoded = encode_image_bytes(original, output_format="jpeg", width=24, height=24)
        self.assertEqual(encoded, original)

    def test_resize_keeps_requested_jpeg(self) -> None:
        encoded = encode_image_bytes(_image_bytes("png", 32, 16), output_format="jpeg", width=64, height=32)
        self.assertEqual(output_format_from_bytes(encoded), "jpeg")
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.size, (64, 32))

    def test_alpha_png_to_jpeg_uses_white_background(self) -> None:
        encoded = encode_image_bytes(_image_bytes("png", 8, 8, alpha=True), output_format="jpeg")
        self.assertEqual(output_format_from_bytes(encoded), "jpeg")
        with Image.open(BytesIO(encoded)) as image:
            self.assertEqual(image.mode, "RGB")

    def test_webp_conversion_preserves_pixels(self) -> None:
        original = _image_bytes("png", 12, 10)
        encoded = encode_image_bytes(original, output_format="webp")
        self.assertEqual(output_format_from_bytes(encoded), "webp")
        with Image.open(BytesIO(original)) as source, Image.open(BytesIO(encoded)) as converted:
            self.assertEqual(source.convert("RGB").tobytes(), converted.convert("RGB").tobytes())


if __name__ == "__main__":
    unittest.main()
