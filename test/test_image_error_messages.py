from __future__ import annotations

import unittest

from services.protocol.conversation import (
    FORCE_IMAGE_GENERATION_INSTRUCTION,
    build_image_prompt,
    force_image_generation_prompt,
    image_stream_error_message,
    is_async_image_tool_text_reply,
    is_skipped_mainline_error,
)
from services.log_service import _image_error_response


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
        # message_as_error 路径常见的精简 body
        self.assertTrue(is_skipped_mainline_error('{"skipped_mainline":true}'))
        self.assertFalse(is_skipped_mainline_error("/backend-api/f/conversation failed: status=400, body=bad request"))

    def test_tool_params_with_prompt_is_async_tool_text(self):
        message = (
            '{"size":"1440x2560","n":1,"prompt":"现代都市风格，照片级写实，8K，超写实。'
            '现代都市真人风格，超写实8K电影级画质，画面比例9:16"}'
        )
        self.assertTrue(is_async_image_tool_text_reply(message))
        self.assertTrue(is_async_image_tool_text_reply('{"size":"1920x1088","n":1}'))
        self.assertTrue(is_async_image_tool_text_reply('{"n":1,"size":"1024x1024","prompt":"a cat"}'))
        self.assertFalse(is_async_image_tool_text_reply("已生成一张角色设定图"))
        self.assertFalse(is_async_image_tool_text_reply('{"prompt":"only prompt"}'))

    def test_decompression_bomb_maps_to_400_encoding_error(self):
        import json

        message = (
            "Image size (275886545 pixels) exceeds limit of 178956970 pixels, "
            "could be decompression bomb DOS attack."
        )
        response = _image_error_response(Exception(message))
        self.assertEqual(response.status_code, 400)
        body = json.loads(response.body)
        self.assertEqual(body["error"]["code"], "encoding_error")
        self.assertEqual(body["error"]["type"], "invalid_request_error")


if __name__ == "__main__":
    unittest.main()
