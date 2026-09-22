from __future__ import annotations

import base64
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image

from services.protocol.conversation import ImageOutput
from services.protocol.openai_v1_image_generations import finalize_image_outputs
from utils.image_format import encode_image_bytes, output_format_from_bytes
from utils.image_tokens import image_size_from_bytes


def _png_b64(width: int, height: int) -> str:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _jpeg_b64(width: int, height: int) -> str:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ImageApiResponseFormatTests(unittest.TestCase):
    def _result(self, width: int, height: int) -> list[ImageOutput]:
        return [
            ImageOutput(kind="progress", model="gpt-image-2", index=1, total=1, text="wait"),
            ImageOutput(
                kind="result",
                model="gpt-image-2",
                index=1,
                total=1,
                data=[{"b64_json": _png_b64(width, height), "revised_prompt": "cat"}],
            ),
        ]

    def test_url_resizes_then_force_saves(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="http://app.test/images/resized.png",
        ) as save:
            finalized = list(finalize_image_outputs(self._result(64, 32), "128x64", "url", "http://app.test"))

        self.assertEqual(finalized[0].kind, "progress")
        item = finalized[1].data[0]
        self.assertEqual(item["url"], "http://app.test/images/resized.png")
        self.assertNotIn("b64_json", item)
        saved_bytes = save.call_args.args[0]
        self.assertEqual(image_size_from_bytes(saved_bytes), (128, 64))
        self.assertEqual(save.call_args.kwargs["force"], True)

    def test_b64_json_resizes_without_force_save(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ) as save:
            finalized = list(finalize_image_outputs(self._result(64, 32), "128x64", "b64_json"))

        item = finalized[1].data[0]
        self.assertIn("b64_json", item)
        self.assertEqual(image_size_from_bytes(base64.b64decode(item["b64_json"])), (128, 64))
        self.assertTrue(all(call.kwargs.get("force") is not True for call in save.call_args_list))

    def test_b64_json_converts_png_to_jpeg_and_resizes(self) -> None:
        with (
            mock.patch(
                "services.protocol.openai_v1_image_generations.save_image_bytes",
                return_value="",
            ),
            mock.patch(
                "services.protocol.openai_v1_image_generations.encode_image_bytes",
                wraps=encode_image_bytes,
            ) as encode,
        ):
            finalized = list(
                finalize_image_outputs(self._result(64, 32), "128x64", "b64_json", output_format="jpeg")
            )

        item = finalized[1].data[0]
        payload = base64.b64decode(item["b64_json"])
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(output_format_from_bytes(payload), "jpeg")
        self.assertEqual(image_size_from_bytes(payload), (128, 64))

    def test_jpeg_source_stays_jpeg_after_resize(self) -> None:
        outputs = [
            ImageOutput(
                kind="result",
                model="gpt-image-2",
                index=1,
                total=1,
                data=[{"b64_json": _jpeg_b64(64, 32), "revised_prompt": "cat"}],
            ),
        ]
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ):
            finalized = list(finalize_image_outputs(outputs, "128x64", "b64_json", output_format="jpeg"))

        payload = base64.b64decode(finalized[0].data[0]["b64_json"])
        self.assertEqual(output_format_from_bytes(payload), "jpeg")
        self.assertEqual(image_size_from_bytes(payload), (128, 64))

    def test_matching_png_keeps_original_b64(self) -> None:
        original = _png_b64(64, 32)
        outputs = [
            ImageOutput(
                kind="result",
                model="gpt-image-2",
                index=1,
                total=1,
                data=[{"b64_json": original, "revised_prompt": "cat"}],
            ),
        ]
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ) as save:
            finalized = list(finalize_image_outputs(outputs, "64x32", "b64_json"))

        self.assertEqual(finalized[0].data[0]["b64_json"], original)
        save.assert_not_called()

    def test_auto_size_keeps_original_pixels(self) -> None:
        original = _png_b64(64, 32)
        for size in ("auto", None, ""):
            with self.subTest(size=size):
                outputs = [
                    ImageOutput(
                        kind="result",
                        model="gpt-image-2",
                        index=1,
                        total=1,
                        data=[{"b64_json": original, "revised_prompt": "cat"}],
                    ),
                ]
                with mock.patch(
                    "services.protocol.openai_v1_image_generations.save_image_bytes",
                    return_value="",
                ) as save:
                    finalized = list(finalize_image_outputs(outputs, size, "b64_json"))

                item = finalized[0].data[0]
                self.assertEqual(item["b64_json"], original)
                self.assertEqual(image_size_from_bytes(base64.b64decode(item["b64_json"])), (64, 32))
                save.assert_not_called()

    def test_auto_size_converts_format_without_resize(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ):
            finalized = list(
                finalize_image_outputs(self._result(64, 32), "AUTO", "b64_json", output_format="jpeg")
            )

        payload = base64.b64decode(finalized[1].data[0]["b64_json"])
        self.assertEqual(output_format_from_bytes(payload), "jpeg")
        self.assertEqual(image_size_from_bytes(payload), (64, 32))

    def test_skips_stretch_when_aspect_ratio_differs(self) -> None:
        original = _png_b64(64, 32)
        outputs = [
            ImageOutput(
                kind="result",
                model="gpt-image-2",
                index=1,
                total=1,
                data=[{"b64_json": original, "revised_prompt": "cat"}],
            ),
        ]
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ) as save:
            finalized = list(finalize_image_outputs(outputs, "128x128", "b64_json"))

        self.assertEqual(finalized[0].data[0]["b64_json"], original)
        self.assertEqual(image_size_from_bytes(base64.b64decode(original)), (64, 32))
        save.assert_not_called()

    def test_converts_format_without_stretch_when_aspect_ratio_differs(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ):
            finalized = list(
                finalize_image_outputs(self._result(64, 32), "128x128", "b64_json", output_format="jpeg")
            )

        payload = base64.b64decode(finalized[1].data[0]["b64_json"])
        self.assertEqual(output_format_from_bytes(payload), "jpeg")
        self.assertEqual(image_size_from_bytes(payload), (64, 32))

    def test_stretches_when_aspect_ratio_within_five_percent(self) -> None:
        with mock.patch(
            "services.protocol.openai_v1_image_generations.save_image_bytes",
            return_value="",
        ):
            finalized = list(finalize_image_outputs(self._result(1024, 1024), "1024x1060", "b64_json"))

        payload = base64.b64decode(finalized[1].data[0]["b64_json"])
        self.assertEqual(image_size_from_bytes(payload), (1024, 1060))


if __name__ == "__main__":
    unittest.main()
