from __future__ import annotations

import unittest

from services.protocol.conversation import (
    FORCE_IMAGE_GENERATION_INSTRUCTION,
    build_image_prompt,
    force_image_generation_prompt,
    image_stream_error_message,
    is_skipped_mainline_error,
)


EMPTY_CONVERSATION_500 = "/backend-api/f/conversation failed: status=500, body="


class ImageErrorMessageTests(unittest.TestCase):
    def test_force_image_generation_prompt_appends_instruction_once(self):
        prompt = "A castle at sunset"

        self.assertEqual(
            force_image_generation_prompt(prompt),
            prompt + FORCE_IMAGE_GENERATION_INSTRUCTION,
        )
        self.assertEqual(
            force_image_generation_prompt(prompt + FORCE_IMAGE_GENERATION_INSTRUCTION),
            prompt + FORCE_IMAGE_GENERATION_INSTRUCTION,
        )

    def test_build_image_prompt_appends_force_instruction(self):
        prompt = "甘州大集超宽横版海报"

        result = build_image_prompt(prompt, "1792x1024", "high")

        self.assertIn("输出图片尺寸为 1792x1024。", result)
        self.assertIn("输出图片质量为 high。", result)
        self.assertTrue(result.endswith(FORCE_IMAGE_GENERATION_INSTRUCTION.strip()))
        self.assertEqual(result.count(FORCE_IMAGE_GENERATION_INSTRUCTION.strip()), 1)
        self.assertEqual(
            force_image_generation_prompt(result),
            result,
        )

    def test_long_prompt_empty_upstream_500_suggests_shortening_prompt(self):
        message = image_stream_error_message(EMPTY_CONVERSATION_500, "a" * 20_001)

        self.assertEqual(message, "The image prompt may be too long. Please shorten it and try again.")

    def test_short_prompt_empty_upstream_500_keeps_upstream_error(self):
        self.assertEqual(image_stream_error_message(EMPTY_CONVERSATION_500, "a" * 20_000), EMPTY_CONVERSATION_500)

    def test_long_prompt_other_upstream_error_is_not_misattributed(self):
        message = image_stream_error_message("/backend-api/f/conversation failed: status=500, body=temporary failure", "a" * 20_001)

        self.assertEqual(message, "/backend-api/f/conversation failed: status=500, body=temporary failure")

    def test_skipped_mainline_error_detection(self):
        self.assertTrue(
            is_skipped_mainline_error(
                '/backend-api/f/conversation failed: status=400, body={"skipped_mainline": true}'
            )
        )
        self.assertFalse(is_skipped_mainline_error("/backend-api/f/conversation failed: status=400, body=bad request"))


if __name__ == "__main__":
    unittest.main()
