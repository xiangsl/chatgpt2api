from __future__ import annotations

import base64
import unittest
from io import BytesIO
from unittest import mock

from PIL import Image

from services.protocol.conversation import ImageOutput
from services.protocol.openai_v1_image_generations import finalize_image_outputs
from utils.image_tokens import image_size_from_bytes


def _png_b64(width: int, height: int) -> str:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=(255, 0, 0)).save(buffer, format="PNG")
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


if __name__ == "__main__":
    unittest.main()
